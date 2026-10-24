from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
import uuid
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from backend.auditor import run_deterministic_audit
from backend.config import settings
from backend.db import (
    SUPPORTED_HOSPITALS,
    SUPPORTED_LANGUAGES,
    SUPPORTED_PAYERS,
    init_db,
)
from backend.demo_data import get_demo_bill, list_demo_Metadata
from backend.llm_service import (
    extract_bill_from_image,
    generate_explanations_and_dispute_letter,
)
from backend.privacy import redact_bill_image, scrub_demo_bill
from backend.schemas import (
    AuditedLineItem,
    AuditReportResponse,
    DemoAuditRequest,
    ExtractedBillSchema,
    GovernanceMetadata,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="MedBill Shield — AI + DuckDB Medical Bill Auditing Platform",
    description=(
        "3-Layer Deterministic Medical Bill Auditor (CMS NCCI Edits + 45 CFR Part 180 MRF Rates + "
        "CA AB 1020 / IRS 501(r) Charity Care) with Local Pillow PII Redaction & Google GenAI."
    ),
    version="1.0.0",
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


def _assemble_audit_response(
    extracted_bill: ExtractedBillSchema,
    hospital_name: str,
    payer_name: str,
    annual_income: float,
    household_size: int,
    language: str,
    redacted_image_base64: str,
    privacy_meta: dict,
    ai_mode: str,
) -> AuditReportResponse:
    effective_hospital = (
        hospital_name.strip()
        if hospital_name and hospital_name.strip()
        else extracted_bill.hospital_name
    )

    audit_data = run_deterministic_audit(
        extracted_bill=extracted_bill,
        hospital_name=effective_hospital,
        payer_name=payer_name,
        annual_income=annual_income,
        household_size=household_size,
    )

    ai_explanation, explanation_mode = generate_explanations_and_dispute_letter(
        audit_data=audit_data,
        hospital_name=effective_hospital,
        payer_name=payer_name,
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
            "redaction_method", "Pillow Top-15% Header Redaction"
        ),
        redacted_region=privacy_meta.get("redacted_region", "Top 15% Header"),
        redacted_fields=privacy_meta.get("redacted_fields", []),
        deterministic_sql_engine="DuckDB Embedded OLAP Engine (0% AI Math Hallucinations)",
        ai_model_used=settings.GEMINI_MODEL,
        ai_mode=combined_ai_mode,
        sql_queries_executed=audit_data["sql_queries_executed"],
    )

    return AuditReportResponse(
        audit_id=f"MBS-{uuid.uuid4().hex[:8].upper()}",
        timestamp=datetime.now(timezone.utc).isoformat(),
        hospital_name=effective_hospital,
        extracted_hospital_name=extracted_bill.hospital_name,
        payer_name=payer_name,
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
        governance=governance,
    )


@app.get("/api/meta")
async def get_meta():
    """Return supported hospitals, insurance payers, languages, and the 3 built-in demo scenarios."""
    return {
        "hospitals": SUPPORTED_HOSPITALS,
        "payers": SUPPORTED_PAYERS,
        "languages": SUPPORTED_LANGUAGES,
        "demos": list_demo_Metadata(),
        "fpl_2026_formula": "fpl_base = 15650 + (household_size - 1) * 5500",
        "charity_care_tiers": [
            {"fpl_range": "<= 200% FPL", "discount": "100% Forgiveness"},
            {"fpl_range": "200% - 400% FPL", "discount": "65% Discount"},
            {"fpl_range": "> 400% FPL", "discount": "0% Discount"},
        ],
    }


@app.post("/api/audit/upload", response_model=AuditReportResponse)
async def audit_uploaded_bill(
    file: UploadFile = File(...),
    hospital_name: str = Form("El Camino Health"),
    payer_name: str = Form("Anthem Blue Cross"),
    annual_income: float = Form(48000.0),
    household_size: int = Form(3),
    language: str = Form("English"),
):
    """
    Step 1: Pillow PII Redaction (Top 15% blackout) ->
    Step 2: Gemini Vision OCR (Structured Outputs) ->
    Step 3: DuckDB 3-Layer Deterministic Audit ->
    Step 4: Gemini Plain-Language Explanation & Formal Dispute Letter.
    """
    raw_bytes = await file.read()
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    # Step 1: Local Pillow PII Header Redaction (Top 15% Blackout)
    redacted_bytes, b64_preview, privacy_meta = redact_bill_image(raw_bytes)

    # Step 2: Gemini 2.5 Flash Structured Vision OCR
    extracted_bill, ocr_mode = extract_bill_from_image(
        redacted_image_bytes=redacted_bytes,
        mime_type="image/png",
        fallback_hospital=hospital_name,
    )

    # Step 3 & 4: Deterministic DuckDB Audit + Dispute Letter Generation
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
async def audit_demo_bill(payload: DemoAuditRequest):
    """
    Run the exact same Local PII Scrubber -> DuckDB 3-Layer Audit -> Dispute Generator
    on one of the 3 realistic pre-loaded demo scenarios.
    """
    demo_raw = get_demo_bill(payload.demo_id)
    effective_hospital = (
        payload.hospital_name.strip()
        if payload.hospital_name and payload.hospital_name.strip()
        else demo_raw["hospital_name"]
    )

    # Step 1: Local PII Scrubbing + Redacted Preview Generation
    extracted_bill, b64_preview, privacy_meta = scrub_demo_bill(
        demo_payload=demo_raw,
        hospital_override=effective_hospital,
    )

    # Step 3 & 4: Deterministic DuckDB Audit + Dispute Letter Generation
    return _assemble_audit_response(
        extracted_bill=extracted_bill,
        hospital_name=effective_hospital,
        payer_name=payload.payer_name,
        annual_income=payload.annual_income,
        household_size=payload.household_size,
        language=payload.language,
        redacted_image_base64=b64_preview,
        privacy_meta=privacy_meta,
        ai_mode="Preset Demo Scenario (Local PII Field & Image Header Scrubber)",
    )


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    """Serve the minimal single-page functional HTML/JS test frontend."""
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        return HTMLResponse(
            content="<h1>MedBill Shield Backend Running</h1><p>static/index.html not found.</p>",
            status_code=200,
        )
    return FileResponse(str(index_path))
