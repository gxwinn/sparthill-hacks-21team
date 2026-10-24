import asyncio
import base64
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import logging
from pathlib import Path
import time
from typing import Any
import uuid

logger = logging.getLogger("uvicorn.error")
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from backend.auditor import run_deterministic_audit
from backend.config import settings
from backend.db import (
    AUTO_DETECT_OPTION,
    LOCAL_MRF_HOSPITALS,
    LOCAL_MRF_PAYERS,
    OTHER_INSURANCE_OPTION,
    SUPPORTED_HOSPITALS,
    SUPPORTED_LANGUAGES,
    SUPPORTED_PAYERS,
    UNINSURED_SELF_PAY_OPTION,
    get_data_governance_sources,
    init_db,
)
from backend.demo_data import get_demo_bill, list_demo_Metadata
from backend.llm_service import (
    _build_deterministic_explanations,
    extract_bill_from_image,
    generate_explanations_and_dispute_letter,
)
from backend.privacy import (
    ensure_sample_bills_seeded,
    match_local_mrf_hospital_and_payer,
    redact_bill_image,
    scrub_demo_bill,
    warmup_ocr_worker,
)
from backend.schemas import (
    AnalyzeRedactedRequest,
    AuditedLineItem,
    AuditReportResponse,
    DemoAuditRequest,
    ExtractedBillSchema,
    GovernanceMetadata,
    RedactedEntityBox,
    RedactionResponse,
    TranslateAuditRequest,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SAMPLE_BILLS_DIR = PROJECT_ROOT / "sample_bills"

# In-memory cache of locally sanitized/redacted images for the Two-Stage Inspection Flow
# Each entry: {"redacted_bytes": ..., "redacted_b64": ..., "privacy_meta": ..., "created_at": float}
_REDACTION_CACHE: dict[str, dict[str, Any]] = {}
_REDACTION_TTL_SECS: float = 1800.0  # 30-minute TTL


def _evict_expired_cache_entries() -> None:
    now = time.monotonic()
    expired = [k for k, v in _REDACTION_CACHE.items() if now - v.get("created_at", 0) > _REDACTION_TTL_SECS]
    for k in expired:
        _REDACTION_CACHE.pop(k, None)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    ensure_sample_bills_seeded(SAMPLE_BILLS_DIR)
    await asyncio.to_thread(warmup_ocr_worker)
    yield


app = FastAPI(
    title="MedBill Shield — AI + DuckDB Medical Bill Auditing Platform",
    description=(
        "Two-Stage Interactive Surgical Local PII Redaction (Offline OCR + Regex/Context + Pillow) & "
        "3-Layer Deterministic Medical Bill Auditor (CMS NCCI Edits + 45 CFR Part 180 MRF Rates + "
        "CA AB 1020 / IRS 501(r) Charity Care) with Google GenAI."
    ),
    version="1.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _resolve_hospital_and_payer(
    extracted_bill: ExtractedBillSchema,
    requested_hospital: str,
    requested_payer: str,
    privacy_meta: dict[str, Any],
) -> dict[str, str]:
    """
    Resolve effective Hospital & Insurance Payer using Smart Auto-Detection with Manual Override:
      - If dropdown is 'Auto-Detect from Bill' (or empty):
          * Matches extracted hospital/payer against Bay Area MRF registry (`LOCAL_MRF_HOSPITALS` / `LOCAL_MRF_PAYERS`).
          * If external hospital/payer is on the document (e.g. Christian Medical College, Star Health),
            preserves the exact document names and sets status to `EXTERNAL_FALLBACK`.
          * If not visible on the document, sets status to `NOT_DETECTED`.
      - If user explicitly selected a specific Hospital or Payer override in the dropdown:
          * Honors the user's manual selection so they can re-analyze under any Bay Area MRF contract.
    """
    detected_hosp = (
        extracted_bill.hospital_name
        or privacy_meta.get("detected_hospital_name")
        or ""
    ).strip()
    detected_payer = (
        extracted_bill.payer_name
        or privacy_meta.get("detected_payer_name")
        or ""
    ).strip()

    matched_hosp, matched_payer = match_local_mrf_hospital_and_payer(
        detected_hosp, detected_payer
    )

    req_hosp = (requested_hospital or "").strip()
    req_payer = (requested_payer or "").strip()

    is_auto_hosp = req_hosp in ("", AUTO_DETECT_OPTION, "AUTO")
    is_auto_payer = req_payer in ("", AUTO_DETECT_OPTION, "AUTO")

    # 1. Resolve Hospital
    if is_auto_hosp:
        if matched_hosp:
            effective_hospital = matched_hosp
            hospital_match_status = "MATCHED_LOCAL_MRF"
        elif detected_hosp:
            effective_hospital = detected_hosp
            hospital_match_status = "EXTERNAL_FALLBACK"
        else:
            effective_hospital = "Other US Hospital"
            hospital_match_status = "NOT_DETECTED"
    else:
        if matched_hosp and req_hosp == matched_hosp:
            effective_hospital = matched_hosp
            hospital_match_status = "MATCHED_LOCAL_MRF"
        elif req_hosp == "Other US Hospital" and detected_hosp and not matched_hosp:
            effective_hospital = detected_hosp
            hospital_match_status = "EXTERNAL_FALLBACK"
        else:
            effective_hospital = req_hosp
            hospital_match_status = (
                "MANUAL_OVERRIDE"
                if (detected_hosp and detected_hosp != req_hosp)
                else "MATCHED_LOCAL_MRF"
            )

    # 2. Resolve Insurance Payer
    if is_auto_payer:
        if matched_payer:
            effective_payer = matched_payer
            payer_match_status = "MATCHED_LOCAL_MRF"
        elif detected_payer:
            effective_payer = detected_payer
            payer_match_status = "EXTERNAL_FALLBACK"
        else:
            # If user manually selected a local MRF hospital to simulate MRF rates, default payer to Anthem Blue Cross.
            # But if the effective hospital is NOT a local MRF hospital (e.g. "Other US Hospital"),
            # always fall back to the CMS Medicare Benchmark regardless of hospital status.
            if (
                effective_hospital in LOCAL_MRF_HOSPITALS
                and hospital_match_status == "MANUAL_OVERRIDE"
            ):
                effective_payer = "Anthem Blue Cross"
                payer_match_status = "MANUAL_OVERRIDE"
            else:
                effective_payer = "CMS Medicare Benchmark"
                payer_match_status = "NOT_DETECTED"
    else:
        if matched_payer and req_payer == matched_payer:
            effective_payer = matched_payer
            payer_match_status = "MATCHED_LOCAL_MRF"
        elif req_payer in (OTHER_INSURANCE_OPTION, "Other Insurance / Out-of-Network"):
            effective_payer = OTHER_INSURANCE_OPTION
            payer_match_status = "MANUAL_OVERRIDE" if detected_payer else "EXTERNAL_FALLBACK"
        elif req_payer in (UNINSURED_SELF_PAY_OPTION, "Uninsured / Self-Pay"):
            effective_payer = UNINSURED_SELF_PAY_OPTION
            payer_match_status = "MANUAL_OVERRIDE" if detected_payer else "EXTERNAL_FALLBACK"
        else:
            effective_payer = req_payer
            payer_match_status = (
                "MANUAL_OVERRIDE"
                if (detected_payer and detected_payer != req_payer)
                else "MATCHED_LOCAL_MRF"
            )

    # If user manually overrode Hospital to a Bay Area MRF hospital while leaving Payer on Auto-Detect
    # on an external bill, also apply Anthem Blue Cross MRF contract so simulation works in 1 click
    if (
        hospital_match_status == "MANUAL_OVERRIDE"
        and effective_hospital in LOCAL_MRF_HOSPITALS
        and is_auto_payer
        and effective_payer not in LOCAL_MRF_PAYERS
    ):
        effective_payer = "Anthem Blue Cross"
        payer_match_status = "MANUAL_OVERRIDE"

    # Build human-readable friendly note explaining which pricing tier was used
    is_uninsured_selected = effective_payer in (
        UNINSURED_SELF_PAY_OPTION,
        "Uninsured / Self-Pay",
        "CMS Medicare Benchmark",
    )
    if (
        effective_hospital in LOCAL_MRF_HOSPITALS
        and effective_payer in LOCAL_MRF_PAYERS
        and "MANUAL_OVERRIDE" not in (hospital_match_status, payer_match_status)
    ):
        banner_msg = (
            f"Matched to Bay Area MRF Registry ({effective_hospital} • {effective_payer}). "
            f"Layer 2 price audit used exact 45 CFR § 180.50 negotiated contract rates."
        )
    elif (
        effective_hospital in LOCAL_MRF_HOSPITALS
        and not is_uninsured_selected
        and effective_payer not in LOCAL_MRF_PAYERS
    ):
        banner_msg = (
            f"Pricing Tier: Hospital Median Negotiated MRF Rate ({effective_hospital}). "
            f"Because '{effective_payer}' is out-of-network or unlisted in the 4-payer MRF table, "
            f"Layer 2 applied {effective_hospital}'s median commercial negotiated rate across all published payers."
        )
    elif is_uninsured_selected and req_payer in (UNINSURED_SELF_PAY_OPTION, "Uninsured / Self-Pay"):
        banner_msg = (
            f"Pricing Tier: Uninsured / Self-Pay Federal Benchmark ({effective_hospital}). "
            f"Layer 2 applied the Federal CMS Medicare Benchmark (1.8x Medicare rate) alongside Layer 1 NCCI coding edits "
            f"and Layer 3 California AB 1020 / IRS § 501(r) Charity Care forgiveness."
        )
    elif "MANUAL_OVERRIDE" in (hospital_match_status, payer_match_status):
        orig_h = detected_hosp or "Unspecified Facility"
        orig_p = detected_payer or "Unspecified Payer"
        tier_desc = (
            f"{effective_hospital} • {effective_payer} MRF contract rates"
            if (effective_hospital in LOCAL_MRF_HOSPITALS and effective_payer in LOCAL_MRF_PAYERS)
            else "Federal CMS Medicare Benchmark (1.8x Medicare rate)"
        )
        banner_msg = (
            f"Manual Override Active (Document listed '{orig_h}' • '{orig_p}'). "
            f"Audited using {tier_desc}."
        )
    elif "NOT_DETECTED" in (hospital_match_status, payer_match_status):
        orig_h = detected_hosp or "Not listed on document"
        orig_p = detected_payer or "Not listed on document"
        banner_msg = (
            f"Detected on document: Facility '{orig_h}', Insurance '{orig_p}'. "
            f"Applied the Federal CMS Medicare Benchmark (1.8x Medicare rate). You can select a specific hospital or insurance plan above to re-run."
        )
    else:
        banner_msg = (
            f"Auto-Detected from Bill: {detected_hosp or effective_hospital} • "
            f"{detected_payer or effective_payer}. Because this facility/insurer is outside the Bay Area MRF registry, "
            f"Layer 2 applied the Federal CMS Medicare Benchmark (1.8x Medicare rate)."
        )

    return {
        "effective_hospital": effective_hospital,
        "effective_payer": effective_payer,
        "extracted_hospital_name": detected_hosp,
        "extracted_payer_name": detected_payer,
        "hospital_match_status": hospital_match_status,
        "payer_match_status": payer_match_status,
        "detection_banner_message": banner_msg,
    }


def _assemble_audit_response(
    extracted_bill: ExtractedBillSchema,
    hospital_name: str,
    payer_name: str,
    annual_income: float,
    household_size: int,
    language: str,
    redacted_image_base64: str,
    privacy_meta: dict[str, Any],
    ai_mode: str,
) -> AuditReportResponse:
    resolved = _resolve_hospital_and_payer(
        extracted_bill=extracted_bill,
        requested_hospital=hospital_name,
        requested_payer=payer_name,
        privacy_meta=privacy_meta,
    )
    effective_hospital = resolved["effective_hospital"]
    effective_payer = resolved["effective_payer"]

    audit_data = run_deterministic_audit(
        extracted_bill=extracted_bill,
        hospital_name=effective_hospital,
        payer_name=effective_payer,
        annual_income=annual_income,
        household_size=household_size,
    )

    if "Live Google GenAI SDK" in ai_mode:
        ai_explanation = _build_deterministic_explanations(
            audit_data=audit_data,
            hospital_name=effective_hospital,
            payer_name=effective_payer,
            language=language,
        )
        explanation_mode = f"Deterministic Multi-Language Legal Engine ({language})"
    else:
        ai_explanation, explanation_mode = generate_explanations_and_dispute_letter(
            audit_data=audit_data,
            hospital_name=effective_hospital,
            payer_name=effective_payer,
            language=language,
        )

    # Map per-line plain-language meanings and explanations back onto audited line items
    exp_by_index = {
        exp.line_index: exp for exp in ai_explanation.line_explanations
    }
    enriched_lines: list[AuditedLineItem] = []
    for line in audit_data["line_items"]:
        exp = exp_by_index.get(line.line_index)
        if exp:
            line.plain_language_meaning = exp.plain_language_meaning
            line.why_flagged = exp.why_flagged
        enriched_lines.append(line)

    combined_ai_mode = (
        ai_mode if ai_mode == explanation_mode else f"{ai_mode} | {explanation_mode}"
    )

    governance = GovernanceMetadata(
        pii_scrubbed_locally=bool(privacy_meta.get("pii_scrubbed_locally", True)),
        phi_bytes_sent_to_cloud=int(privacy_meta.get("phi_bytes_sent_to_cloud", 0)),
        redaction_method=privacy_meta.get(
            "redaction_method",
            "Surgical Local OCR Bounding-Box Redaction (Offline OCR + Regex/Context + Pillow)",
        ),
        redacted_region=privacy_meta.get(
            "redacted_region", "Surgical Word-Level Bounding Boxes"
        ),
        redacted_fields=privacy_meta.get("redacted_fields", []),
        redacted_entity_count=int(privacy_meta.get("redacted_entity_count", 0)),
        detected_pii_categories=privacy_meta.get("detected_pii_categories", []),
        whitelisted_medical_items_preserved=int(
            privacy_meta.get("whitelisted_medical_items_preserved", 0)
        ),
        ocr_engine_used=privacy_meta.get(
            "ocr_engine_used", "Offline Local OCR Engine"
        ),
        deterministic_sql_engine="DuckDB Embedded OLAP Engine (Loaded from data/*.csv via read_csv_auto)",
        ai_model_used=settings.GEMINI_MODEL,
        ai_mode=combined_ai_mode,
        sql_queries_executed=audit_data["sql_queries_executed"],
        data_provenance_sources=get_data_governance_sources(),
    )

    return AuditReportResponse(
        audit_id=f"MBS-{uuid.uuid4().hex[:8].upper()}",
        timestamp=datetime.now(timezone.utc).isoformat(),
        hospital_name=effective_hospital,
        extracted_hospital_name=resolved["extracted_hospital_name"],
        payer_name=effective_payer,
        extracted_payer_name=resolved["extracted_payer_name"],
        hospital_match_status=resolved["hospital_match_status"],
        payer_match_status=resolved["payer_match_status"],
        pricing_benchmark_used=audit_data.get("pricing_benchmark_used", "LOCAL_MRF"),
        detection_banner_message=resolved["detection_banner_message"],
        language=language,
        is_itemized=audit_data["is_itemized"],
        requires_ub04_request=audit_data["requires_ub04_request"],
        total_billed=audit_data["total_billed"],
        layer_1_coding_errors_removed=audit_data["layer_1_coding_errors_removed"],
        layer_2_mrf_overcharge_removed=audit_data["layer_2_mrf_overcharge_removed"],
        subtotal_after_layer_2=audit_data["subtotal_after_layer_2"],
        layer_3_charity_care_forgiveness=audit_data["layer_3_charity_care_forgiveness"],
        total_savings=audit_data["total_savings"],
        final_patient_balance=audit_data["final_patient_balance"],
        charity_care=audit_data["charity_care"],
        line_items=enriched_lines,
        plain_language_summary=ai_explanation.overall_summary,
        dispute_letter=ai_explanation.dispute_letter,
        redacted_image_base64=redacted_image_base64,
        original_image_base64=privacy_meta.get("original_image_base64", ""),
        governance=governance,
    )


@app.get("/api/meta")
async def get_meta():
    """Return supported hospitals, insurance payers, languages, 1-click demos, sample bills, and data provenance."""
    return {
        "hospitals": SUPPORTED_HOSPITALS,
        "local_mrf_hospitals": LOCAL_MRF_HOSPITALS,
        "payers": SUPPORTED_PAYERS,
        "local_mrf_payers": LOCAL_MRF_PAYERS,
        "languages": SUPPORTED_LANGUAGES,
        "demos": list_demo_Metadata(),
        "sample_bills": ensure_sample_bills_seeded(SAMPLE_BILLS_DIR),
        "data_provenance_sources": get_data_governance_sources(),
        "fpl_2026_formula": "fpl_base = 15650 + (household_size - 1) * 5500",
        "charity_care_tiers": [
            {"fpl_range": "<= 200% FPL", "discount": "100% Forgiveness"},
            {"fpl_range": "200% - 400% FPL", "discount": "65% Discount"},
            {"fpl_range": "> 400% FPL", "discount": "0% Discount"},
        ],
    }


@app.get("/api/sample-bills")
@app.get("/api/samples")
async def list_sample_bills():
    """Dynamically scan `sample_bills/` at the project root and return all selectable bill images."""
    return {"sample_bills": ensure_sample_bills_seeded(SAMPLE_BILLS_DIR)}


@app.get("/api/sample-bills/{filename}")
@app.get("/api/samples/{filename}")
async def get_sample_bill_image(filename: str):
    """Serve a sample medical bill image from the root `sample_bills/` directory."""
    ensure_sample_bills_seeded(SAMPLE_BILLS_DIR)
    safe_name = Path(filename).name
    target = (SAMPLE_BILLS_DIR / safe_name).resolve()
    if not target.exists() or not target.is_file() or target.parent != SAMPLE_BILLS_DIR.resolve():
        raise HTTPException(status_code=404, detail=f"Sample bill '{filename}' not found.")
    return FileResponse(str(target))


@app.post("/api/redact", response_model=RedactionResponse)
@app.post("/api/audit/redact", response_model=RedactionResponse)
async def redact_bill_stage_1(
    file: UploadFile | None = File(default=None),
    sample_filename: str | None = Form(default=None),
):
    """
    Stage 1 of Two-Stage Interactive PII Redaction Flow:
    Runs offline local OCR to obtain word bounding boxes, applies Regex/context matching
    and medical procedure whitelisting, and uses Pillow to draw solid black boxes over
    sensitive PII directly on the image before any bytes leave the device.
    """
    raw_bytes: bytes | None = None
    if file is not None:
        raw_bytes = await file.read()
    elif sample_filename:
        ensure_sample_bills_seeded(SAMPLE_BILLS_DIR)
        safe_name = Path(sample_filename).name
        sample_path = (SAMPLE_BILLS_DIR / safe_name).resolve()
        if (
            not sample_path.exists()
            or not sample_path.is_file()
            or sample_path.parent != SAMPLE_BILLS_DIR.resolve()
        ):
            raise HTTPException(
                status_code=404,
                detail=f"Sample bill '{sample_filename}' not found in sample_bills/.",
            )
        raw_bytes = sample_path.read_bytes()

    if not raw_bytes:
        raise HTTPException(
            status_code=400,
            detail="Please provide an uploaded bill image or select a sample bill from sample_bills/.",
        )

    try:
        redacted_bytes, redacted_b64, privacy_meta = await asyncio.to_thread(
            redact_bill_image, raw_bytes
        )
    except ValueError as exc:
        logger.warning("Rejected invalid image upload in /api/redact: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    redaction_id = f"RED-{uuid.uuid4().hex[:10].upper()}"
    orig_b64 = privacy_meta.pop("original_image_base64", "")

    _evict_expired_cache_entries()
    if len(_REDACTION_CACHE) >= 50:
        oldest_key = next(iter(_REDACTION_CACHE))
        _REDACTION_CACHE.pop(oldest_key, None)

    _REDACTION_CACHE[redaction_id] = {
        "redacted_bytes": redacted_bytes,
        "redacted_b64": redacted_b64,
        "orig_b64": orig_b64,
        "privacy_meta": privacy_meta,
        "created_at": time.monotonic(),
    }

    entities = [
        RedactedEntityBox(**ent) for ent in privacy_meta.get("redacted_entities", [])
    ]

    return RedactionResponse(
        redaction_id=redaction_id,
        original_image_base64=orig_b64,
        redacted_image_base64=redacted_b64,
        redacted_count=int(privacy_meta.get("redacted_entity_count", len(entities))),
        detected_pii_categories=privacy_meta.get("detected_pii_categories", []),
        redacted_entities=entities,
        whitelisted_items_preserved=int(
            privacy_meta.get("whitelisted_medical_items_preserved", 0)
        ),
        ocr_engine_used=privacy_meta.get(
            "ocr_engine_used", "Offline Local OCR Engine"
        ),
        phi_bytes_sent_to_cloud=0,
        detected_hospital_name=privacy_meta.get("detected_hospital_name", ""),
        detected_payer_name=privacy_meta.get("detected_payer_name", ""),
        matched_local_hospital=privacy_meta.get("matched_local_hospital", ""),
        matched_local_payer=privacy_meta.get("matched_local_payer", ""),
        privacy_meta=privacy_meta,
    )


@app.post("/api/analyze", response_model=AuditReportResponse)
@app.post("/api/audit/analyze", response_model=AuditReportResponse)
def analyze_redacted_bill_stage_2(payload: AnalyzeRedactedRequest):
    """
    Stage 2 of Two-Stage Interactive PII Redaction Flow:
    Takes the already-sanitized medical bill image confirmed by the user in Step 2,
    runs Gemini Vision OCR (with local OCR fallback) + 3-Layer Deterministic DuckDB Audit,
    and returns the full savings breakdown and dispute letter.
    """
    cached = _REDACTION_CACHE.get(payload.redaction_id) if payload.redaction_id else None
    if cached:
        redacted_bytes: bytes = cached["redacted_bytes"]
        b64_preview: str = cached["redacted_b64"]
        privacy_meta: dict[str, Any] = cached["privacy_meta"]
    elif payload.redacted_image_base64:
        b64_preview = payload.redacted_image_base64
        raw_b64 = (
            b64_preview.split(",", 1)[1] if "," in b64_preview else b64_preview
        )
        try:
            redacted_bytes = base64.b64decode(raw_b64)
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail="Invalid redacted_image_base64 payload."
            ) from exc
        privacy_meta = payload.privacy_meta or {
            "pii_scrubbed_locally": True,
            "phi_bytes_sent_to_cloud": 0,
            "redaction_method": "Surgical Local OCR Bounding-Box Redaction (Verified in Stage 1)",
        }
    else:
        raise HTTPException(
            status_code=400,
            detail="Redacted session expired or missing. Please run Step 1 (Scrub PII Locally) first.",
        )

    fallback_hosp = (
        ""
        if payload.hospital_name in ("", AUTO_DETECT_OPTION, "AUTO")
        else payload.hospital_name
    )
    extracted_bill, ocr_mode = extract_bill_from_image(
        redacted_image_bytes=redacted_bytes,
        mime_type="image/png",
        fallback_hospital=fallback_hosp,
    )
    if not extracted_bill.is_valid_medical_document or not extracted_bill.line_items:
        detail_msg = (
            extracted_bill.rejection_reason
            or "No medical billing data, CPT/HCPCS codes, or hospital charges were detected in this image. Please upload a valid medical bill or clinical statement."
        )
        logger.warning("Rejected non-medical image in /api/analyze: %s", detail_msg)
        raise HTTPException(status_code=422, detail=detail_msg)

    return _assemble_audit_response(
        extracted_bill=extracted_bill,
        hospital_name=payload.hospital_name,
        payer_name=payload.payer_name,
        annual_income=payload.annual_income,
        household_size=payload.household_size,
        language=payload.language,
        redacted_image_base64=b64_preview,
        privacy_meta=privacy_meta,
        ai_mode=ocr_mode,
    )


@app.post("/api/audit/upload", response_model=AuditReportResponse)
async def audit_uploaded_bill(
    file: UploadFile = File(...),
    hospital_name: str = Form("Auto-Detect from Bill"),
    payer_name: str = Form("Auto-Detect from Bill"),
    annual_income: float = Form(48000.0),
    household_size: int = Form(3),
    language: str = Form("English"),
):
    """
    Step 1: Surgical Local OCR PII Redaction (Word Bounding Boxes + Regex/Context + Pillow) ->
    Step 2: Gemini Vision OCR (Structured Outputs) ->
    Step 3: DuckDB 3-Layer Deterministic Audit ->
    Step 4: Gemini Plain-Language Explanation & Formal Dispute Letter.
    """
    raw_bytes = await file.read()
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        redacted_bytes, b64_preview, privacy_meta = redact_bill_image(raw_bytes)
    except ValueError as exc:
        logger.warning("Rejected invalid image upload in /api/audit/upload: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    fallback_hosp = (
        ""
        if hospital_name in ("", AUTO_DETECT_OPTION, "AUTO")
        else hospital_name
    )
    extracted_bill, ocr_mode = extract_bill_from_image(
        redacted_image_bytes=redacted_bytes,
        mime_type="image/png",
        fallback_hospital=fallback_hosp,
    )
    if not extracted_bill.is_valid_medical_document or not extracted_bill.line_items:
        detail_msg = (
            extracted_bill.rejection_reason
            or "No medical billing data, CPT/HCPCS codes, or hospital charges were detected in this image. Please upload a valid medical bill or clinical statement."
        )
        logger.warning("Rejected non-medical image in /api/analyze: %s", detail_msg)
        raise HTTPException(status_code=422, detail=detail_msg)

    return _assemble_audit_response(
        extracted_bill=extracted_bill,
        hospital_name=hospital_name,
        payer_name=payer_name,
        annual_income=annual_income,
        household_size=household_size,
        language=language,
        redacted_image_base64=b64_preview,
        privacy_meta=privacy_meta,
        ai_mode=ocr_mode,
    )


@app.post("/api/audit/demo", response_model=AuditReportResponse)
def audit_demo_bill(payload: DemoAuditRequest):
    """
    Run the full 3-Layer Deterministic DuckDB Audit on one of the 3 built-in demo scenarios.
    """
    demo = get_demo_bill(payload.demo_id)
    if not demo:
        raise HTTPException(
            status_code=404, detail=f"Unknown demo_id '{payload.demo_id}'."
        )

    hosp_override = (
        None
        if payload.hospital_name in ("", AUTO_DETECT_OPTION, "AUTO")
        else payload.hospital_name
    )
    extracted_bill, b64_preview, privacy_meta = scrub_demo_bill(
        demo_payload=demo,
        hospital_override=hosp_override,
    )

    return _assemble_audit_response(
        extracted_bill=extracted_bill,
        hospital_name=payload.hospital_name,
        payer_name=payload.payer_name,
        annual_income=payload.annual_income,
        household_size=payload.household_size,
        language=payload.language,
        redacted_image_base64=b64_preview,
        privacy_meta=privacy_meta,
        ai_mode="Preset Demo Scenario (Local PII Redaction + Deterministic DuckDB Audit)",
    )


@app.post("/api/audit/translate", response_model=AuditReportResponse)
@app.post("/api/translate", response_model=AuditReportResponse)
def translate_audit_report(payload: TranslateAuditRequest):
    """
    Fast translation endpoint:
    Instantly re-explains and translates the existing audit report into the requested language,
    including plain-language summary, line item explanations, and formal dispute letter,
    without re-running vision OCR or DuckDB.
    """
    report = payload.audit_report
    target_lang = payload.language or "English"

    audit_data = {
        "is_itemized": report.is_itemized,
        "requires_ub04_request": report.requires_ub04_request,
        "total_billed": report.total_billed,
        "layer_1_coding_errors_removed": report.layer_1_coding_errors_removed,
        "layer_2_mrf_overcharge_removed": report.layer_2_mrf_overcharge_removed,
        "subtotal_after_layer_2": report.subtotal_after_layer_2,
        "layer_3_charity_care_forgiveness": report.layer_3_charity_care_forgiveness,
        "total_savings": report.total_savings,
        "final_patient_balance": report.final_patient_balance,
        "charity_care": report.charity_care,
        "line_items": report.line_items,
        "sql_queries_executed": report.governance.sql_queries_executed if report.governance else [],
    }

    ai_explanation = _build_deterministic_explanations(
        audit_data=audit_data,
        hospital_name=report.hospital_name,
        payer_name=report.payer_name,
        language=target_lang,
    )
    mode = f"Instant Multi-Language Legal Translator ({target_lang})"

    exp_by_index = {
        exp.line_index: exp for exp in ai_explanation.line_explanations
    }
    updated_lines: list[AuditedLineItem] = []
    for line in report.line_items:
        exp = exp_by_index.get(line.line_index)
        if exp:
            line.plain_language_meaning = exp.plain_language_meaning
            line.why_flagged = exp.why_flagged
        updated_lines.append(line)

    updated_report = report.model_copy(deep=True)
    updated_report.language = target_lang
    updated_report.plain_language_summary = ai_explanation.overall_summary
    updated_report.dispute_letter = ai_explanation.dispute_letter
    updated_report.line_items = updated_lines
    if updated_report.governance:
        updated_report.governance.ai_mode = f"{updated_report.governance.ai_mode} | {mode}"

    return updated_report


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        return HTMLResponse("<h1>MedBill Shield Backend Running</h1>")
    return HTMLResponse(index_path.read_text(encoding="utf-8"))
