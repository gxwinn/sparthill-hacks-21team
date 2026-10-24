from datetime import date
import json
import logging
import time
from typing import Any
from google import genai
from google.genai import types
from backend.config import settings
from backend.schemas import (
    AIExplanationResponse,
    AuditedLineItem,
    CharityCareSummary,
    ExtractedBillSchema,
    LineExplanationSchema,
    RawLineItem,
)

logger = logging.getLogger("uvicorn.error")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

# Deprecated Gemini 2.0 / 2.5 model IDs that return 404 NOT_FOUND for new AI Studio keys
DEPRECATED_MODEL_MAP: dict[str, str] = {
    "gemini-2.5-flash-lite": "gemini-3.5-flash-lite",
    "models/gemini-2.5-flash-lite": "gemini-3.5-flash-lite",
    "gemini-2.5-flash": "gemini-3.5-flash-lite",
    "models/gemini-2.5-flash": "gemini-3.5-flash-lite",
    "gemini-2.0-flash": "gemini-3.5-flash-lite",
    "models/gemini-2.0-flash": "gemini-3.5-flash-lite",
    "gemini-1.5-flash": "gemini-3.5-flash-lite",
}

FALLBACK_GEMINI_MODELS: list[str] = [
    "gemini-3.5-flash-lite",
    "gemini-3.5-flash",
    "gemini-flash-latest",
]


def _resolve_active_gemini_models() -> list[str]:
    """
    Return the ordered list of Gemini model identifiers to attempt, automatically
    upgrading retired 2.0/2.5 model IDs that return 404 NOT_FOUND on Google AI Studio.
    """
    configured = (settings.GEMINI_MODEL or "gemini-3.5-flash-lite").strip()
    primary = DEPRECATED_MODEL_MAP.get(configured.lower(), configured)
    if primary != configured:
        logger.warning(
            "Configured GEMINI_MODEL '%s' is deprecated/retired (404 NOT_FOUND); "
            "automatically upgrading to '%s'.",
            configured,
            primary,
        )
    ordered = [primary]
    for candidate in FALLBACK_GEMINI_MODELS:
        if candidate not in ordered:
            ordered.append(candidate)
    return ordered

# Multi-language CPT plain-language dictionary for instant fallback or enrichment
CPT_TRANSLATIONS: dict[str, dict[str, str]] = {
    "99285": {
        "English": "High-severity Emergency Room visit (Level 5) requiring urgent evaluation and complex medical decision-making.",
        "Russian": "Визит в отделение неотложной помощи высокой степени тяжести (уровень 5), требующий срочного обследования.",
        "Spanish": "Visita a la sala de emergencias de alta gravedad (Nivel 5) que requiere evaluación urgente y decisiones médicas complejas.",
        "Vietnamese": "Khám cấp cứu mức độ nặng (Cấp độ 5) đòi hỏi đánh giá khẩn cấp và xử lý y khoa phức tạp.",
    },
    "99283": {
        "English": "Moderate-severity Emergency Room visit (Level 3) for acute illness or injury evaluation.",
        "Russian": "Визит в отделение неотложной помощи средней тяжести (уровень 3) для осмотра и диагностики.",
        "Spanish": "Visita a la sala de emergencias de gravedad moderada (Nivel 3) para evaluación de lesión o enfermedad aguda.",
        "Vietnamese": "Khám cấp cứu mức độ trung bình (Cấp độ 3) để kiểm tra chấn thương hoặc bệnh cấp tính.",
    },
    "70551": {
        "English": "MRI scan of the brain and brain stem without contrast dye.",
        "Russian": "МРТ головного мозга без контрастного вещества.",
        "Spanish": "Resonancia magnética (RM) del cerebro sin medio de contraste.",
        "Vietnamese": "Chụp cộng hưởng từ (MRI) sọ não không tiêm thuốc tương phản.",
    },
    "71045": {
        "English": "Single-view chest X-ray image to check lungs, heart, and chest wall.",
        "Russian": "Рентген грудной клетки в одной проекции для проверки легких и сердца.",
        "Spanish": "Radiografía de tórax de una sola vista para examinar pulmones y corazón.",
        "Vietnamese": "Chụp X-quang ngực một tư thế để kiểm tra phổi và tim.",
    },
    "12001": {
        "English": "Simple stitching/repair of a superficial skin wound (up to 2.5 cm).",
        "Russian": "Простое наложение швов и обработка поверхностной раны кожи (до 2,5 см).",
        "Spanish": "Reparación simple con sutura de una herida superficial de la piel (hasta 2.5 cm).",
        "Vietnamese": "Khâu và xử lý vết thương ngoài da đơn giản (dưới 2,5 cm).",
    },
    "99070": {
        "English": "General surgical tray, gauze, and routine medical supplies used during a procedure.",
        "Russian": "Стандартный хирургический лоток, перевязочные и расходные материалы во время процедуры.",
        "Spanish": "Bandeja quirúrgica general, gasas e insumos estándar utilizados durante un procedimiento.",
        "Vietnamese": "Khay dụng cụ phẫu thuật tiêu chuẩn, băng gạc và vật tư tiêu hao cơ bản.",
    },
    "36415": {
        "English": "Routine needle blood draw from a vein (venipuncture) for lab testing.",
        "Russian": "Стандартный забор крови из вены (венепункция) для лабораторных анализов.",
        "Spanish": "Extracción de sangre de rutina por punción venosa para análisis de laboratorio.",
        "Vietnamese": "Lấy máu tĩnh mạch thường quy để làm xét nghiệm.",
    },
    "80053": {
        "English": "Comprehensive Metabolic Panel (CMP) — 14 blood tests checking kidney, liver, electrolytes, and blood sugar.",
        "Russian": "Полная метаболическая панель (14 биохимических показателей крови: печень, почки, глюкоза, электролиты).",
        "Spanish": "Panel Metabólico Completo (14 pruebas en sangre de riñón, hígado, glucosa y electrolitos).",
        "Vietnamese": "Xét nghiệm sinh hóa máu toàn diện (14 chỉ số đánh giá chức năng gan, thận, đường huyết, điện giải).",
    },
    "80048": {
        "English": "Basic Metabolic Panel (BMP) — 8 blood tests that are already a subset of the 14-test Comprehensive Metabolic Panel (80053).",
        "Russian": "Базовая метаболическая панель (8 тестов крови, которые уже полностью входят в состав полной панели 80053).",
        "Spanish": "Panel Metabólico Básico (8 pruebas en sangre que ya están incluidas dentro del Panel Completo 80053).",
        "Vietnamese": "Xét nghiệm sinh hóa máu cơ bản (8 chỉ số vốn đã nằm trong gói xét nghiệm toàn diện 80053).",
    },
    "85025": {
        "English": "Complete Blood Count (CBC) with automated white blood cell differential.",
        "Russian": "Общий анализ крови (ОАК) с автоматической лейкоцитарной формулой.",
        "Spanish": "Hemograma completo (CBC) con recuento diferencial automatizado de glóbulos blancos.",
        "Vietnamese": "Tổng phân tích tế bào máu ngoại vi (CBC) tự động có công thức bạch cầu.",
    },
    "85027": {
        "English": "Standard Automated Complete Blood Count (CBC) without differential.",
        "Russian": "Стандартный автоматический общий анализ крови (ОАК) без лейкоцитарной формулы.",
        "Spanish": "Hemograma completo (CBC) automatizado estándar sin diferencial.",
        "Vietnamese": "Tổng phân tích tế bào máu (CBC) tự động tiêu chuẩn.",
    },
    "93306": {
        "English": "Complete transthoracic echocardiogram (ultrasound of the heart) with Doppler and color flow mapping.",
        "Russian": "Полная трансторакальная эхокардиография (УЗИ сердца) с допплерографией и цветным картированием.",
        "Spanish": "Ecocardiograma transtorácico completo (ultrasonido del corazón) con Doppler y flujo a color.",
        "Vietnamese": "Siêu âm tim qua thành ngực toàn diện có Doppler và bản đồ dòng chảy màu.",
    },
    "80061": {
        "English": "Lipid Panel — blood test measuring total cholesterol, HDL, LDL, and triglycerides.",
        "Russian": "Липидная панель — анализ крови на общий холестерин, ЛПВП, ЛПНП и триглицериды.",
        "Spanish": "Perfil lipídico — análisis de sangre que mide colesterol total, HDL, LDL y triglicéridos.",
        "Vietnamese": "Bộ xét nghiệm mỡ máu (Lipid Panel) — đo cholesterol toàn phần, HDL, LDL và triglyceride.",
    },
    "0250": {
        "English": "General hospital pharmacy services and routine inpatient/outpatient medication dispensing (Revenue Code 0250).",
        "Russian": "Общие аптечные услуги больницы и базовые медикаменты (код дохода UB-04 0250).",
        "Spanish": "Servicios generales de farmacia hospitalaria y medicamentos básicos (Código de ingresos 0250).",
        "Vietnamese": "Dịch vụ dược bệnh viện tổng quát và cấp phát thuốc thông thường (Mã doanh thu 0250).",
    },
    "92250": {
        "English": "Fundus photography / retinal imaging exam to screen for diabetic retinopathy and eye disease.",
        "Russian": "Фотографирование глазного дна (осмотр сетчатки при диабетической ретинопатии).",
        "Spanish": "Fotografía de fondo de ojo / examen de retina para detección de retinopatía diabética.",
        "Vietnamese": "Chụp ảnh đáy mắt / khám võng mạc tầm soát bệnh võng mạc tiểu đường.",
    },
    "0120": {
        "English": "Hospital inpatient room and board — semi-private two-bed room (Revenue Code 0120).",
        "Russian": "Пребывание и питание в стационаре — двухместная полуприватная палата (код дохода 0120).",
        "Spanish": "Habitación y alimentación hospitalaria — habitación semiprivada de dos camas (Código 0120).",
        "Vietnamese": "Tiền giường và nội trú bệnh viện — phòng bán tư nhân hai giường (Mã doanh thu 0120).",
    },
}


def _has_valid_api_key() -> bool:
    key = (settings.GEMINI_API_KEY or "").strip()
    return bool(key) and key != "your_gemini_api_key_here"


def extract_bill_from_image(
    redacted_image_bytes: bytes,
    mime_type: str = "image/png",
    fallback_hospital: str = "",
) -> tuple[ExtractedBillSchema, str]:
    """
    Step 2: Extract structured hospital_name, payer_name, and line_items from the
    surgically PII-redacted medical bill image using Google GenAI (`gemini-3.5-flash-lite`)
    with local offline OCR verification and strict non-medical image rejection.
    """
    from backend.privacy import (
        extract_bill_via_local_ocr,
        normalize_and_filter_extracted_bill,
    )

    local_extracted = extract_bill_via_local_ocr(
        image_bytes=redacted_image_bytes,
        fallback_hospital=fallback_hospital,
    )

    if _has_valid_api_key():
        client = genai.Client(
            api_key=settings.GEMINI_API_KEY,
            http_options={"timeout": 30000},
        )
        prompt = (
            "You are an expert medical billing auditor OCR system. "
            "Examine this image carefully.\n"
            "CRITICAL EXTRACTION & VALIDATION RULES:\n"
            "1. FIRST, determine whether this image is actually a medical billing statement, hospital invoice, "
            "Explanation of Benefits (EOB), or clinical discharge summary (`is_valid_medical_document`).\n"
            "   - If the image is a random photograph (e.g. a landscape, nature scene, person, animal, object, meme), "
            "a non-medical receipt, or contains no healthcare billing/clinical procedures, you MUST set "
            "`is_valid_medical_document = false`, `line_items = []`, and set `rejection_reason` to a clear explanation "
            "(e.g. 'The uploaded image appears to be a non-medical photograph/landscape and contains no hospital billing or clinical procedure data.').\n"
            "2. If it IS a valid medical document (`is_valid_medical_document = true`), extract `hospital_name` "
            "(exact facility name on the header, or empty string if not shown) and `payer_name` "
            "(exact insurance payer/plan name, or empty string if not shown).\n"
            "3. Extract ONLY actual medical procedures, diagnostic tests, pharmacy/supplies, and facility services into `line_items`.\n"
            "4. STRICTLY EXCLUDE financial summary, footer, subtotal, adjustment, discount, tax, payment, or balance-due rows "
            "(e.g. 'Total Billed Charges', 'Total Gross Billed', 'Insurance Adjustments', 'PATIENT AMOUNT DUE', 'Balance Due', 'Subtotal', 'Amount Paid').\n"
            "5. For each service row, separate out any leading service date (e.g. '05/22/2026' must NOT be placed in `description`), "
            "put the 5-character CPT/HCPCS code (e.g. '93306', '80061', '71045', '92250') OR 4-digit hospital revenue code (e.g. '0250', '0120') "
            "into `cpt_code`, put ONLY the clean procedure name into `description` (e.g. 'Echocardiogram Complete'), and extract `quantity` and `billed_amount`.\n"
            "6. Set `is_itemized` to True whenever valid 5-digit CPT/HCPCS or 4-digit revenue codes are present."
        )

        last_exc: Exception | None = None
        for model_name in _resolve_active_gemini_models():
            t0 = time.perf_counter()
            try:
                logger.info(
                    "Invoking Gemini Vision OCR (model=%s, image_bytes=%d)...",
                    model_name,
                    len(redacted_image_bytes),
                )
                response = client.models.generate_content(
                    model=model_name,
                    contents=[
                        types.Part.from_bytes(
                            data=redacted_image_bytes,
                            mime_type=mime_type or "image/png",
                        ),
                        prompt,
                    ],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=ExtractedBillSchema,
                        temperature=0.1,
                    ),
                )
                elapsed = time.perf_counter() - t0
                parsed_candidate: ExtractedBillSchema | None = None
                if response.parsed and isinstance(response.parsed, ExtractedBillSchema):
                    parsed_candidate = response.parsed
                elif response.text:
                    data = json.loads(response.text)
                    parsed_candidate = ExtractedBillSchema(**data)

                if parsed_candidate is not None:
                    # If Gemini explicitly identified the image as a non-medical photo/document
                    if not parsed_candidate.is_valid_medical_document:
                        reason = (
                            parsed_candidate.rejection_reason
                            or "The uploaded image does not appear to be a medical bill or clinical statement."
                        )
                        logger.warning(
                            "Gemini Vision (model=%s, %.2fs) rejected non-medical image: %s",
                            model_name,
                            elapsed,
                            reason,
                        )
                        return (
                            ExtractedBillSchema(
                                is_valid_medical_document=False,
                                rejection_reason=reason,
                                hospital_name="",
                                payer_name="",
                                is_itemized=False,
                                line_items=[],
                            ),
                            f"Live Google GenAI SDK ({model_name} Vision Validation)",
                        )

                    normalized = normalize_and_filter_extracted_bill(parsed_candidate)
                    if normalized.line_items:
                        if local_extracted:
                            if not normalized.hospital_name and local_extracted.hospital_name:
                                normalized.hospital_name = local_extracted.hospital_name
                            if not normalized.payer_name and local_extracted.payer_name:
                                normalized.payer_name = local_extracted.payer_name
                        logger.info(
                            "Gemini Vision OCR succeeded (model=%s, %.2fs, extracted_items=%d, hospital='%s').",
                            model_name,
                            elapsed,
                            len(normalized.line_items),
                            normalized.hospital_name,
                        )
                        return (
                            normalized,
                            f"Live Google GenAI SDK ({model_name} Vision Structured Output)",
                        )

                    # Gemini returned 0 line items; if local OCR extracted clinical/discharge items, return those immediately
                    if local_extracted and local_extracted.line_items:
                        if parsed_candidate.hospital_name and not local_extracted.hospital_name:
                            local_extracted.hospital_name = parsed_candidate.hospital_name
                        if parsed_candidate.payer_name and not local_extracted.payer_name:
                            local_extracted.payer_name = parsed_candidate.payer_name
                        logger.info(
                            "Gemini Vision (model=%s, %.2fs) validated clinical document; using %d items from Local Clinical OCR.",
                            model_name,
                            elapsed,
                            len(local_extracted.line_items),
                        )
                        return (
                            normalize_and_filter_extracted_bill(local_extracted),
                            f"Live Google GenAI SDK ({model_name} Vision) + Local Clinical OCR",
                        )

                    reason = (
                        parsed_candidate.rejection_reason
                        or "No medical billing line items, CPT/HCPCS codes, or hospital charges were found in the uploaded image."
                    )
                    logger.warning(
                        "Gemini Vision (model=%s, %.2fs) found 0 medical line items in image: %s",
                        model_name,
                        elapsed,
                        reason,
                    )
                    return (
                        ExtractedBillSchema(
                            is_valid_medical_document=False,
                            rejection_reason=reason,
                            hospital_name="",
                            payer_name="",
                            is_itemized=False,
                            line_items=[],
                        ),
                        f"Live Google GenAI SDK ({model_name} Vision Validation)",
                    )
            except Exception as exc:
                elapsed = time.perf_counter() - t0
                last_exc = exc
                logger.error(
                    "Gemini Vision OCR request failed on model '%s' after %.2fs [%s]: %s",
                    model_name,
                    elapsed,
                    type(exc).__name__,
                    exc,
                )
                continue

        fallback_reason = (
            f"Deterministic Local OCR Engine (Gemini Vision fallback after {type(last_exc).__name__})"
            if last_exc
            else "Deterministic Local OCR Engine (Extracted directly from redacted bill image)"
        )
    else:
        logger.info("GEMINI_API_KEY not configured; using offline Local OCR Engine.")
        fallback_reason = (
            "Deterministic Offline OCR Mode (Set GEMINI_API_KEY in .env for live Gemini Vision OCR)"
        )

    if local_extracted and local_extracted.line_items:
        return normalize_and_filter_extracted_bill(local_extracted), fallback_reason

    # Never fabricate or return a mock bill when an uploaded image has no medical billing content
    rejection_msg = (
        "No medical billing data, CPT/HCPCS procedure codes, or hospital statement charges were detected "
        "in the uploaded image. Please upload a valid medical bill or clinical statement."
    )
    logger.warning("Local OCR found no medical billing data in uploaded image; rejecting non-bill image.")
    return (
        ExtractedBillSchema(
            is_valid_medical_document=False,
            rejection_reason=rejection_msg,
            hospital_name="",
            payer_name="",
            is_itemized=False,
            line_items=[],
        ),
        fallback_reason,
    )


def generate_explanations_and_dispute_letter(
    audit_data: dict[str, Any],
    hospital_name: str,
    payer_name: str,
    language: str,
) -> tuple[AIExplanationResponse, str]:
    """
    Step 4: Use google-genai (`gemini-3.5-flash-lite`) with Structured Outputs (`response_schema`)
    to generate:
      1. Plain-language summary & per-CPT explanations in the user's requested language.
      2. A formal, legally cited Dispute & Financial Assistance Appeal Letter in English.
    """
    audited_lines: list[AuditedLineItem] = audit_data["line_items"]
    charity_care: CharityCareSummary = audit_data["charity_care"]
    is_itemized: bool = audit_data["is_itemized"]

    if _has_valid_api_key():
        client = genai.Client(
            api_key=settings.GEMINI_API_KEY,
            http_options={"timeout": 30000},
        )
        serializable_lines = [line.model_dump() for line in audited_lines]
        audit_payload = {
            "hospital_name": hospital_name,
            "payer_name": payer_name,
            "target_language": language,
            "is_itemized": is_itemized,
            "requires_ub04_request": audit_data["requires_ub04_request"],
            "total_billed": audit_data["total_billed"],
            "layer_1_coding_errors_removed": audit_data[
                "layer_1_coding_errors_removed"
            ],
            "layer_2_mrf_overcharge_removed": audit_data[
                "layer_2_mrf_overcharge_removed"
            ],
            "subtotal_after_layer_2": audit_data["subtotal_after_layer_2"],
            "layer_3_charity_care_forgiveness": audit_data[
                "layer_3_charity_care_forgiveness"
            ],
            "final_patient_balance": audit_data["final_patient_balance"],
            "charity_care": charity_care.model_dump(),
            "line_items": serializable_lines,
        }

        prompt = (
            f"You are a senior medical billing advocate and health care regulatory attorney.\n"
            f"Review these deterministic DuckDB 3-Layer Audit results (0% math hallucinations):\n"
            f"{json.dumps(audit_payload, indent=2)}\n\n"
            f"Generate a structured JSON response matching AIExplanationResponse:\n"
            f"1. `overall_summary`: Plain-language executive summary of the audit outcome in {language}.\n"
            f"2. `line_explanations`: For every line item (matching `line_index` and `cpt_code`), provide "
            f"`plain_language_meaning` and `why_flagged` translated into {language}.\n"
            f"3. `dispute_letter`: A formal, ready-to-send legal dispute letter in {language} addressed to {hospital_name} "
            f"Patient Financial Services & Billing Compliance Department. "
            f"If `is_itemized` is False, write a formal 'HIPAA Itemized Bill (Form CMS-1450 / UB-04) Request Letter' "
            f"citing 45 CFR § 164.524 and demanding a halt to billing collections until CPT/HCPCS codes are supplied. "
            f"If `is_itemized` is True, write a formal 'Medical Bill Dispute & Financial Assistance Appeal Letter' "
            f"citing the exact CPT codes, CMS NCCI edit violations, 45 CFR Part 180 Hospital Price Transparency MRF "
            f"negotiated rates for {payer_name}, and California AB 1020 / IRS § 501(r) charity care calculations. "
            f"Translate all headings, body text, and formal demands into {language}."
        )

        last_exc: Exception | None = None
        for model_name in _resolve_active_gemini_models():
            t0 = time.perf_counter()
            try:
                logger.info(
                    "Invoking Gemini Explanation & Dispute Letter Generator (model=%s, language=%s)...",
                    model_name,
                    language,
                )
                response = client.models.generate_content(
                    model=model_name,
                    contents=[prompt],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=AIExplanationResponse,
                        temperature=0.1,
                    ),
                )
                elapsed = time.perf_counter() - t0
                if response.parsed and isinstance(response.parsed, AIExplanationResponse):
                    logger.info(
                        "Gemini Explanation & Dispute Letter succeeded (model=%s, %.2fs).",
                        model_name,
                        elapsed,
                    )
                    return (
                        response.parsed,
                        f"Live Google GenAI SDK ({model_name} Structured Output)",
                    )
                if response.text:
                    data = json.loads(response.text)
                    logger.info(
                        "Gemini Explanation & Dispute Letter JSON succeeded (model=%s, %.2fs).",
                        model_name,
                        elapsed,
                    )
                    return (
                        AIExplanationResponse(**data),
                        f"Live Google GenAI SDK ({model_name} JSON)",
                    )
            except Exception as exc:
                elapsed = time.perf_counter() - t0
                last_exc = exc
                logger.error(
                    "Gemini Explanation generation failed on model '%s' after %.2fs [%s]: %s",
                    model_name,
                    elapsed,
                    type(exc).__name__,
                    exc,
                )
                continue

        mode_label = (
            f"Deterministic Multi-Language Engine (Gemini fallback: {type(last_exc).__name__})"
            if last_exc
            else "Deterministic Multi-Language Engine"
        )
    else:
        mode_label = (
            "Deterministic Multi-Language Engine (Offline / No GEMINI_API_KEY Required)"
        )

    return (
        _build_deterministic_explanations(
            audit_data=audit_data,
            hospital_name=hospital_name,
            payer_name=payer_name,
            language=language,
        ),
        mode_label,
    )


def _build_deterministic_explanations(
    audit_data: dict[str, Any],
    hospital_name: str,
    payer_name: str,
    language: str,
) -> AIExplanationResponse:
    lang = language if language in ("English", "Russian", "Spanish", "Vietnamese") else "English"
    audited_lines: list[AuditedLineItem] = audit_data["line_items"]
    charity_care: CharityCareSummary = audit_data["charity_care"]
    is_itemized: bool = audit_data["is_itemized"]

    total_billed = audit_data["total_billed"]
    l1 = audit_data["layer_1_coding_errors_removed"]
    l2 = audit_data["layer_2_mrf_overcharge_removed"]
    l3 = audit_data["layer_3_charity_care_forgiveness"]
    final_bal = audit_data["final_patient_balance"]
    total_saved = audit_data["total_savings"]

    line_explanations: list[LineExplanationSchema] = []
    for line in audited_lines:
        cpt = line.cpt_code.strip().upper()
        meaning = CPT_TRANSLATIONS.get(cpt, {}).get(
            lang,
            _default_meaning_translation(line.description, is_itemized, lang),
        )
        why_flagged = _translate_why_flagged(line, payer_name, lang)
        line_explanations.append(
            LineExplanationSchema(
                line_index=line.line_index,
                cpt_code=line.cpt_code,
                plain_language_meaning=meaning,
                why_flagged=why_flagged,
            )
        )

    overall_summary = _translate_overall_summary(
        is_itemized=is_itemized,
        hospital_name=hospital_name,
        payer_name=payer_name,
        total_billed=total_billed,
        l1=l1,
        l2=l2,
        l3=l3,
        total_saved=total_saved,
        final_bal=final_bal,
        fpl_pct=charity_care.user_fpl_pct,
        discount_pct=charity_care.discount_pct,
        lang=lang,
    )

    if not is_itemized:
        dispute_letter = _generate_ub04_request_letter(
            hospital_name=hospital_name,
            payer_name=payer_name,
            total_billed=total_billed,
            audited_lines=audited_lines,
            charity_care=charity_care,
            lang=lang,
        )
    else:
        dispute_letter = _generate_formal_dispute_letter(
            hospital_name=hospital_name,
            payer_name=payer_name,
            audit_data=audit_data,
            lang=lang,
        )

    return AIExplanationResponse(
        overall_summary=overall_summary,
        line_explanations=line_explanations,
        dispute_letter=dispute_letter,
    )


def _default_meaning_translation(
    description: str, is_itemized: bool, lang: str
) -> str:
    if not is_itemized:
        return {
            "English": f"Consolidated hospital summary charge ('{description}') with no 5-digit CPT/HCPCS code.",
            "Russian": f"Сводный больничный счет («{description}») без 5-значного медицинского кода CPT/HCPCS.",
            "Spanish": f"Cargo hospitalario resumido ('{description}') sin código médico CPT/HCPCS de 5 dígitos.",
            "Vietnamese": f"Khoản thu gộp của bệnh viện ('{description}') không có mã thủ thuật CPT/HCPCS 5 chữ số.",
        }[lang]
    return description


def _translate_why_flagged(
    line: AuditedLineItem, payer_name: str, lang: str
) -> str:
    if line.status == "NCCI_VIOLATION":
        return {
            "English": (
                f"ILLEGAL UNBUNDLING (-${line.layer_1_deduction:,.2f}): Under federal CMS NCCI rules, this service is already bundled into the primary procedure and cannot be billed separately. ({line.violation_reason})"
            ),
            "Russian": (
                f"НЕЗАКОННОЕ РАЗДЕЛЕНИЕ УСЛУГ (-${line.layer_1_deduction:,.2f}): По федеральным правилам CMS NCCI эта услуга уже включена в основную процедуру и не может оплачиваться отдельно."
            ),
            "Spanish": (
                f"DESGLOSE ILEGAL NCCI (-${line.layer_1_deduction:,.2f}): Según las normas federales CMS NCCI, este servicio ya está incluido en el procedimiento principal y no puede cobrarse por separado."
            ),
            "Vietnamese": (
                f"TÁCH DỊCH VỤ TRÁI PHÉP (-${line.layer_1_deduction:,.2f}): Theo quy định CMS NCCI liên bang, dịch vụ này đã nằm trọn gói trong thủ thuật chính và không được phép tính tiền riêng."
            ),
        }[lang]

    if line.status == "DUPLICATE":
        return {
            "English": (
                f"DUPLICATE BILLING (-${line.layer_1_deduction:,.2f}): CPT {line.cpt_code} was billed more than once on the same encounter statement without a valid repeat modifier."
            ),
            "Russian": (
                f"ДУБЛИРОВАНИЕ СЧЕТА (-${line.layer_1_deduction:,.2f}): Код CPT {line.cpt_code} был выставлен дважды в одном счете без законного основания."
            ),
            "Spanish": (
                f"COBRO DUPLICADO (-${line.layer_1_deduction:,.2f}): El código CPT {line.cpt_code} se facturó más de una vez en el mismo estado de cuenta."
            ),
            "Vietnamese": (
                f"TÍNH TIỀN TRÙNG LẶP (-${line.layer_1_deduction:,.2f}): Mã CPT {line.cpt_code} bị tính hai lần trên cùng một hóa đơn mà không có căn cứ hợp lệ."
            ),
        }[lang]

    if line.status == "REVENUE_CODE_ROLLUP":
        return {
            "English": (
                f"UNITEMIZED UB-04 REVENUE CODE ROLL-UP (-${line.layer_1_deduction:,.2f}): Hospital billed vague 4-digit Revenue Code {line.cpt_code} (${line.billed_amount:,.2f}) without disclosing the required 5-digit HCPCS/NDC drug or supply code. Unsupported markup above the ${line.allowed_amount:,.2f} Medicare baseline is disallowed."
            ),
            "Russian": (
                f"НЕДЕТАЛИЗИРОВАННЫЙ КОД ДОХОДА UB-04 (-${line.layer_1_deduction:,.2f}): Больница выставила общий 4-значный код {line.cpt_code} (${line.billed_amount:,.2f}) без обязательного 5-значного кода препарата/расходника HCPCS/NDC. Необоснованная наценка сверх базы Medicare (${line.allowed_amount:,.2f}) списана."
            ),
            "Spanish": (
                f"CARGO AGRUPADO UB-04 SIN DESGLOSAR (-${line.layer_1_deduction:,.2f}): El hospital facturó el código genérico de 4 dígitos {line.cpt_code} (${line.billed_amount:,.2f}) sin revelar el código específico HCPCS/NDC de 5 dígitos. Se elimina el sobreprecio sobre la base de Medicare (${line.allowed_amount:,.2f})."
            ),
            "Vietnamese": (
                f"MÃ DOANH THU UB-04 GOM GỘP THIẾU CHI TIẾT (-${line.layer_1_deduction:,.2f}): Bệnh viện tính mã 4 chữ số chung {line.cpt_code} (${line.billed_amount:,.2f}) mà không công bố mã thuốc/vật tư 5 chữ số HCPCS/NDC. Phần chênh lệch vượt mức cơ sở Medicare (${line.allowed_amount:,.2f}) bị loại bỏ."
            ),
        }[lang]

    if line.status == "OVERCHARGED":
        return {
            "English": (
                f"MRF CONTRACTUAL OVERCHARGE (-${line.layer_2_deduction:,.2f}): Hospital billed gross chargemaster price (${line.billed_amount:,.2f}), which exceeds the published {payer_name} negotiated rate of ${line.allowed_amount:,.2f} (Medicare benchmark: ${line.medicare_rate:,.2f})."
            ),
            "Russian": (
                f"ЗАВЫШЕНИЕ ТАРИФА MRF (-${line.layer_2_deduction:,.2f}): Больница выставила максимальный прайс (${line.billed_amount:,.2f}) вместо официального согласованного тарифа {payer_name} в размере ${line.allowed_amount:,.2f} (тариф Medicare: ${line.medicare_rate:,.2f})."
            ),
            "Spanish": (
                f"SOBRECARGO SOBRE TARIFA MRF (-${line.layer_2_deduction:,.2f}): El hospital cobró el precio bruto (${line.billed_amount:,.2f}), superando la tarifa negociada publicada de {payer_name} de ${line.allowed_amount:,.2f} (referencia Medicare: ${line.medicare_rate:,.2f})."
            ),
            "Vietnamese": (
                f"VƯỢT GIÁ NIÊM YẾT MRF (-${line.layer_2_deduction:,.2f}): Bệnh viện tính giá gốc (${line.billed_amount:,.2f}), cao hơn mức giá thỏa thuận công khai của {payer_name} là ${line.allowed_amount:,.2f} (mức chuẩn Medicare: ${line.medicare_rate:,.2f})."
            ),
        }[lang]

    if line.status == "MISSING_CPT":
        return {
            "English": (
                "MISSING CPT CODE: You have a federal right under HIPAA (45 CFR § 164.524) to demand a fully itemized UB-04 statement with 5-digit CPT codes before paying."
            ),
            "Russian": (
                "ОТСУТСТВУЕТ КОД CPT: По федеральному закону HIPAA (45 CFR § 164.524) вы имеете право потребовать детализированный счет по форме UB-04 с 5-значными кодами CPT до оплаты."
            ),
            "Spanish": (
                "FALTA CÓDIGO CPT: Usted tiene el derecho federal bajo HIPAA (45 CFR § 164.524) de exigir una factura detallada UB-04 con códigos CPT de 5 dígitos antes de pagar."
            ),
            "Vietnamese": (
                "THIẾU MÃ CPT: Theo luật liên bang HIPAA (45 CFR § 164.524), bạn có quyền yêu cầu bảng kê chi tiết mẫu UB-04 có đủ mã CPT 5 chữ số trước khi thanh toán."
            ),
        }[lang]

    return {
        "English": f"VALID CHARGE: Within the published {payer_name} negotiated rate (${line.allowed_amount:,.2f}).",
        "Russian": f"КОРРЕКТНЫЙ СЧЕТ: Соответствует опубликованному тарифу {payer_name} (${line.allowed_amount:,.2f}).",
        "Spanish": f"CARGO VÁLIDO: Dentro de la tarifa negociada publicada de {payer_name} (${line.allowed_amount:,.2f}).",
        "Vietnamese": f"HỢP LỆ: Nằm trong mức giá thỏa thuận công khai của {payer_name} (${line.allowed_amount:,.2f}).",
    }[lang]


def _translate_overall_summary(
    is_itemized: bool,
    hospital_name: str,
    payer_name: str,
    total_billed: float,
    l1: float,
    l2: float,
    l3: float,
    total_saved: float,
    final_bal: float,
    fpl_pct: float,
    discount_pct: float,
    lang: str,
) -> str:
    if not is_itemized:
        return {
            "English": (
                f"SUMMARY BILL DETECTED: {hospital_name} billed ${total_billed:,.2f} using vague department totals without 5-digit CPT/HCPCS procedure codes. "
                f"Price & NCCI checks are paused. We generated a formal HIPAA Right-of-Access & Itemized UB-04 Request Letter to freeze collections until {hospital_name} discloses every CPT code. "
                f"(Note: At {fpl_pct:.1f}% of the 2026 Federal Poverty Level, your household also qualifies for a {discount_pct:.0f}% statutory Charity Care reduction under CA AB 1020 / IRS § 501(r) once itemized.)"
            ),
            "Russian": (
                f"ОБНАРУЖЕН СВОДНЫЙ СЧЕТ БЕЗ КОДОВ CPT: Больница {hospital_name} выставила ${total_billed:,.2f} общими суммами без 5-значных кодов CPT/HCPCS. "
                f"Проверка цен и NCCI приостановлена. Сформировано официальное требование по закону HIPAA о предоставлении детализированной формы UB-04 и заморозке взыскания. "
                f"(При доходе {fpl_pct:.1f}% от прожиточного минимума FPL ваша семья также имеет право на {discount_pct:.0f}% списание по закону CA AB 1020 / IRS § 501(r))."
            ),
            "Spanish": (
                f"FACTURA RESUMIDA DETECTADA: {hospital_name} facturó ${total_billed:,.2f} sin códigos de procedimiento CPT/HCPCS de 5 dígitos. "
                f"Se generó una Carta Formal bajo HIPAA solicitando la factura detallada UB-04 y suspendiendo el cobro. "
                f"(Además, con un ingreso del {fpl_pct:.1f}% del Nivel Federal de Pobreza, su hogar califica para un {discount_pct:.0f}% de descuento por Asistencia Financiera bajo CA AB 1020 / IRS § 501(r))."
            ),
            "Vietnamese": (
                f"PHÁT HIỆN HÓA ĐƠN TÓM TẮT THIẾU MÃ CPT: {hospital_name} đã tính ${total_billed:,.2f} mà không liệt kê mã thủ thuật CPT/HCPCS 5 chữ số. "
                f"Hệ thống đã tạo Thư Yêu Cầu Bảng Kê Chi Tiết UB-04 theo luật HIPAA để tạm dừng thu nợ. "
                f"(Ở mức {fpl_pct:.1f}% chuẩn nghèo liên bang FPL, gia đình bạn còn đủ điều kiện được giảm {discount_pct:.0f}% theo luật Từ thiện Y tế CA AB 1020 / IRS § 501(r))."
            ),
        }[lang]

    return {
        "English": (
            f"3-Layer Deterministic Audit Complete for {hospital_name} ({payer_name}): Out of ${total_billed:,.2f} billed, "
            f"Layer 1 removed ${l1:,.2f} in illegal CMS NCCI unbundled/duplicate coding errors, "
            f"Layer 2 removed ${l2:,.2f} inchargemaster overcharges above {payer_name}'s published MRF rates, and "
            f"Layer 3 applied a {discount_pct:.0f}% statutory Charity Care discount (-${l3:,.2f} at {fpl_pct:.1f}% FPL under CA AB 1020 / IRS § 501(r)), "
            f"saving ${total_saved:,.2f} and reducing your final balance to ${final_bal:,.2f}."
        ),
        "Russian": (
            f"3-уровневый детерминированный аудит счета {hospital_name} ({payer_name}) завершен: из общей суммы ${total_billed:,.2f} "
            f"Уровень 1 исключил ${l1:,.2f} за незаконное разделение и дублирование кодов (CMS NCCI), "
            f"Уровень 2 списал ${l2:,.2f} за превышение официальных тарифов MRF для {payer_name}, а "
            f"Уровень 3 применил законную скидку по программе финансовой помощи {discount_pct:.0f}% (-${l3:,.2f} при доходе {fpl_pct:.1f}% FPL по закону CA AB 1020 / IRS § 501(r)). "
            f"Общая экономия составила ${total_saved:,.2f}, итого к оплате: ${final_bal:,.2f}."
        ),
        "Spanish": (
            f"Auditoría Determinista de 3 Capas completada para {hospital_name} ({payer_name}): De un total facturado de ${total_billed:,.2f}, "
            f"la Capa 1 eliminó ${l1:,.2f} por errores ilegales de codificación NCCI y duplicados, "
            f"la Capa 2 redujo ${l2:,.2f} por sobrecargos sobre las tarifas MRF publicadas de {payer_name}, y "
            f"la Capa 3 aplicó un {discount_pct:.0f}% de descuento legal por Caridad Médica (-${l3:,.2f} al {fpl_pct:.1f}% del FPL bajo CA AB 1020 / IRS § 501(r)), "
            f"ahorrando ${total_saved:,.2f} y reduciendo su saldo final a ${final_bal:,.2f}."
        ),
        "Vietnamese": (
            f"Hoàn tất Kiểm toán 3 Lớp cho {hospital_name} ({payer_name}): Trên tổng hóa đơn ${total_billed:,.2f}, "
            f"Lớp 1 đã loại bỏ ${l1:,.2f} phí tách mã/trùng lặp trái phép theo CMS NCCI, "
            f"Lớp 2 cắt giảm ${l2:,.2f} tiền chênh lệch vượt giá thỏa thuận MRF của {payer_name}, và "
            f"Lớp 3 áp dụng mức miễn giảm Hỗ trợ Tài chính {discount_pct:.0f}% (-${l3:,.2f} ở mức {fpl_pct:.1f}% FPL theo luật CA AB 1020 / IRS § 501(r)), "
            f"giúp tiết kiệm tổng cộng ${total_saved:,.2f} và giảm số tiền cần thanh toán xuống còn ${final_bal:,.2f}."
        ),
    }[lang]


def _generate_ub04_request_letter(
    hospital_name: str,
    payer_name: str,
    total_billed: float,
    audited_lines: list[AuditedLineItem],
    charity_care: CharityCareSummary,
    lang: str = "English",
) -> str:
    today_str = date.today().isoformat()
    if lang == "Spanish":
        lines_bullet = "\n".join(
            f"  - {line.description}: ${line.billed_amount:,.2f} (Código CPT/HCPCS: NO PROPORCIONADO)"
            for line in audited_lines
        )
        return f"""FECHA: {today_str}

PARA: Servicios Financieros al Paciente y Oficial de Cumplimiento HIPAA
    {hospital_name}
    Ref: EXIGENCIA FORMAL DE FACTURA DETALLADA (FORMULARIO CMS-1450 / UB-04) Y SUSPENSIÓN DE COBRANZA
    Aseguradora en Archivo: {payer_name}
    Saldo Resumido en Disputa: ${total_billed:,.2f}

Estimado Director de Cumplimiento y Facturación:

Por medio de la presente, presento una disputa formal respecto al estado de cuenta resumido no desglosado por un total de ${total_billed:,.2f} emitido por {hospital_name}, ejerciendo mis derechos estatutarios federales bajo la Regla de Privacidad HIPAA (45 CFR § 164.524), la Ley No Surprises Act (Ley Pública 116-260) y las regulaciones de Transparencia de Precios Hospitalarios de CMS (45 CFR Parte 180).

1. FACTURA DEFECTUOSA SIN CÓDIGOS DE PROCEDIMIENTO CPT/HCPCS
El estado de cuenta entregado contiene únicamente cargos globales agrupados sin códigos CPT o HCPCS de 5 dígitos:
{lines_bullet}

Sin códigos CPT/HCPCS de 5 dígitos ni códigos de ingresos hospitalarios, resulta imposible verificar este documento contra las reglas federales de empaquetamiento NCCI de CMS o comprobar las tarifas negociadas según 45 CFR § 180.50.

2. EXIGENCIA FORMAL DE DERECHO DE ACCESO HIPAA PARA UB-04 / CMS-1450
Conforme a 45 CFR § 164.524(b)(2), exijo que {hospital_name} proporcione en un plazo de treinta (30) días calendario:
  (a) Un estado de cuenta institucional desglosado línea por línea (Formulario CMS-1450 / UB-04 y/o CMS-1500);
  (b) El código CPT/HCPCS de 5 dígitos, NDC y unidades para cada cargo; y
  (c) Copia completa de la auditoría de codificación médica para esta atención.

3. NOTIFICACIÓN DE ELEGIBILIDAD PARA ATENCIÓN CARITATIVA (CA AB 1020 Y CÓDIGO IRS § 501(r))
Hago constar además que mi hogar consta de {charity_care.household_size} personas con un ingreso anual de ${charity_care.annual_income:,.2f}, situándonos al {charity_care.user_fpl_pct:.1f}% del Nivel Federal de Pobreza 2026. Según la Ley de Salud y Seguridad de California § 127405 (AB 1020) y el Código IRS § 501(r), tenemos derecho legal a un descuento del {charity_care.discount_pct:.0f}% en cualquier saldo pendiente una vez desglosado.

EXIGENCIA DE SUSPENSIÓN INMEDIATA DE COBRANZA:
De conformidad con el Código de Salud y Seguridad de California § 127425 e IRS § 501(r)(6), {hospital_name} debe suspender de inmediato todas las gestiones de cobro, devengo de intereses e informes a agencias de crédito mientras se tramita esta solicitud.

Atentamente,

[Firma del Paciente / Representante Autorizado]
Titular de la Cuenta — Enviado mediante Correo Certificado y Portal del Paciente"""

    if lang == "Vietnamese":
        lines_bullet = "\n".join(
            f"  - {line.description}: ${line.billed_amount:,.2f} (Mã CPT/HCPCS: KHÔNG CÓ)"
            for line in audited_lines
        )
        return f"""NGÀY: {today_str}

KÍNH GỬI: Phòng Tài chính Bệnh nhân & Cán bộ Tuân thủ HIPAA
    {hospital_name}
    V/v: YÊU CẦU CUNG CẤP BẢNG KÊ CHI TIẾT (MẪU CMS-1450 / UB-04) VÀ TẠM HOÃN THU HÓA ĐƠN
    Đơn vị Bảo hiểm ghi nhận: {payer_name}
    Số tiền Tóm tắt Đang khiếu nại: ${total_billed:,.2f}

Kính gửi Ban Giám đốc Tuân thủ & Tài chính Bệnh nhân:

Tôi viết thư này để chính thức khiếu nại bản tóm tắt viện phí chưa được bóc tách với tổng số tiền là ${total_billed:,.2f} do {hospital_name} phát hành, đồng thời thực thi quyền lợi theo Luật Bảo mật Thông tin Y tế HIPAA (45 CFR § 164.524), Đạo luật No Surprises Act và Quy định Công khai Giá Bệnh viện của CMS (45 CFR Phần 180).

1. BẢNG TỔNG HỢP VIỆN PHÍ THIẾU MÃ THỦ THUẬT CPT/HCPCS
Hóa đơn chỉ bao gồm các khoản gom gộp chung chung mà không có mã thủ thuật CPT/HCPCS 5 chữ số:
{lines_bullet}

2. YÊU CẦU CUNG CẤP BẢNG KÊ CHI TIẾT MẪU UB-04 / CMS-1450 THEO QUYỀN TRUY CẬP HIPAA
Căn cứ 45 CFR § 164.524(b)(2), tôi yêu cầu {hospital_name} cung cấp trong vòng 30 ngày:
  (a) Bảng kê chi tiết toàn bộ các khoản mục (Mẫu CMS-1450 / UB-04);
  (b) Mã thủ thuật CPT/HCPCS 5 chữ số, mã thuốc NDC và số lượng cụ thể;
  (c) Nhật ký kiểm toán bảng giá và mã dịch vụ cho đợt điều trị này.

3. THÔNG BÁO VỀ ĐỦ ĐIỀU KIỆN NHẬN HỖ TRỢ VIỆN PHÍ (CA AB 1020 & IRS § 501(r))
Hộ gia đình tôi gồm {charity_care.household_size} người với thu nhập hàng năm ${charity_care.annual_income:,.2f}, đạt {charity_care.user_fpl_pct:.1f}% chuẩn nghèo FPL 2026. Theo luật California AB 1020 và IRS § 501(r), gia đình tôi đủ điều kiện được giảm {charity_care.discount_pct:.0f}% viện phí.

YÊU CẦU TẠM DỪNG HOẠT ĐỘNG THU NỢ:
Căn cứ Bộ luật Sức khỏe California § 127425 và IRS § 501(r)(6), bệnh viện phải đình chỉ mọi hoạt động đòi nợ trong thời gian xử lý khiếu nại này.

Trân trọng,

[Chữ ký Bệnh nhân / Người Đại diện]
Chủ tài khoản — Gửi qua Thư bảo đảm & Cổng thông tin Bệnh nhân"""

    if lang == "Russian":
        lines_bullet = "\n".join(
            f"  - {line.description}: ${line.billed_amount:,.2f} (Код CPT/HCPCS: НЕ УКАЗАН)"
            for line in audited_lines
        )
        return f"""ДАТА: {today_str}

КОМУ: Отдел финансовых услуг пациентам и инспектору по комплаенсу HIPAA
    {hospital_name}
    Тема: ОФИЦИАЛЬНОЕ ТРЕБОВАНИЕ ДЕТАЛИЗИРОВАННОГО СЧЕТА (ФОРМА CMS-1450 / UB-04) И ПРИОСТАНОВКИ ВЗЫСКАНИЯ
    Страховой план: {payer_name}
    Оспариваемая сумма по сводному счету: ${total_billed:,.2f}

Уважаемый руководитель отдела комплаенса и финансовых расчетов:

Настоящим письмом заявляю официальное несогласие со сводным счетом на общую сумму ${total_billed:,.2f}, выставленным {hospital_name}, и реализую свои права в соответствии с федеральным законом HIPAA (45 CFR § 164.524), законом No Surprises Act и правилами ценовой прозрачности CMS (45 CFR Part 180).

1. СВОДНЫЙ СЧЕТ НЕ СОДЕРЖИТ 5-ЗНАЧНЫХ КОДОВ CPT/HCPCS
Предоставленный счет содержит лишь обобщенные статьи расходов без указания кодов CPT/HCPCS:
{lines_bullet}

Без указания 5-значных кодов процедур и кодов доходов невозможно проверить обоснованность начислений по правилам CMS NCCI и тарифам MRF (45 CFR § 180.50).

2. ТРЕБОВАНИЕ ПРЕДОСТАВЛЕНИЯ ФОРМЫ UB-04 / CMS-1450 (HIPAA RIGHT OF ACCESS)
На основании 45 CFR § 164.524(b)(2) требую от {hospital_name} предоставить в течение 30 календарных дней:
  (а) Полный построчно детализированный институциональный счет (форма CMS-1450 / UB-04);
  (б) Точные 5-значные коды CPT/HCPCS, коды NDC и количество единиц;
  (в) Полный отчет внутреннего аудита начислений по данному обращению.

3. УВЕДОМЛЕНИЕ О ПРАВЕ НА БЛАГОТВОРИТЕЛЬНУЮ ПОМОЩЬ (CA AB 1020 И IRS § 501(r))
Состав моей семьи: {charity_care.household_size} чел., совокупный годовой доход: ${charity_care.annual_income:,.2f} ({charity_care.user_fpl_pct:.1f}% от федерального порога бедности FPL 2026). По закону CA AB 1020 и ст. 501(r) Налогового кодекса США наша семья имеет право на скидку {charity_care.discount_pct:.0f}%.

ТРЕБОВАНИЕ О ПРИОСТАНОВКЕ ВЗЫСКАНИЯ:
В силу норм California Health & Safety Code § 127425 и IRS § 501(r)(6) требую незамедлительно приостановить все действия по взысканию задолженности.

С уважением,

[Подпись пациента / законного представителя]
Владелец счета — Направлено заказным письмом и через личный кабинет"""

    lines_bullet = "\n".join(
        f"  - {line.description}: ${line.billed_amount:,.2f} (CPT/HCPCS Code: MISSING)"
        for line in audited_lines
    )
    return f"""DATE: {today_str}

TO: Patient Financial Services & HIPAA Compliance Officer
    {hospital_name}
    Re: FORMAL DEMAND FOR ITEMIZED STATEMENT (FORM CMS-1450 / UB-04) & SUSPENSION OF BILLING
    Insurance Payer on File: {payer_name}
    Disputed Summary Balance: ${total_billed:,.2f}

Dear Billing Compliance Officer:

I am writing to formally dispute the non-itemized summary billing statement totaling ${total_billed:,.2f} issued by {hospital_name}, and to exercise my federal statutory rights under the Health Insurance Portability and Accountability Act (HIPAA) Privacy Rule, 45 CFR § 164.524, the No Surprises Act (Public Law 116-260), and CMS Hospital Price Transparency regulations (45 CFR Part 180).

1. DEFECTIVE SUMMARY STATEMENT LACKING CPT/HCPCS CODES
The statement provided contains only consolidated departmental summary charges without 5-digit Current Procedural Terminology (CPT) or Healthcare Common Procedure Coding System (HCPCS) codes:
{lines_bullet}

Without 5-digit CPT/HCPCS codes, revenue codes, and unit quantities, neither the patient nor the payer ({payer_name}) can audit this statement against CMS National Correct Coding Initiative (NCCI) bundling edits or verify compliance with {hospital_name}'s published Machine-Readable File (MRF) negotiated rates under 45 CFR § 180.50.

2. FORMAL HIPAA RIGHT-OF-ACCESS DEMAND FOR UB-04 / CMS-1450
Pursuant to 45 CFR § 164.524(b)(2), I hereby demand that {hospital_name} provide within thirty (30) calendar days:
  (a) A complete, line-by-line itemized institutional billing statement (Form CMS-1450 / UB-04 and/or Form CMS-1500);
  (b) The exact 5-digit CPT/HCPCS procedure code, National Drug Code (NDC), revenue code, and unit quantity for each charge; and
  (c) A copy of the complete coding and charge master audit trail for this encounter.

3. NOTICE OF STATUTORY CHARITY CARE ELIGIBILITY (CA AB 1020 & IRS § 501(r))
Please also take notice that my household size is {charity_care.household_size} with an annual income of ${charity_care.annual_income:,.2f}, which places our household at {charity_care.user_fpl_pct:.1f}% of the 2026 Federal Poverty Level (Base: ${charity_care.fpl_base_2026:,.2f}). Under California Health & Safety Code § 127405 (AB 1020) and Internal Revenue Code § 501(r)(4)-(5), our household is legally entitled to a {charity_care.discount_pct:.0f}% Financial Assistance reduction on any valid remaining balance once properly itemized.

DEMAND FOR IMMEDIATE HOLD ON COLLECTIONS:
Pursuant to California Health & Safety Code § 127425 and IRS § 501(r)(6), {hospital_name} must immediately suspend all collection activities, interest accrual, and credit bureau reporting while this itemized UB-04 request and Financial Assistance application are pending.

Sincerely,

[Patient / Authorized Representative Signature]
Account Holder — Sent via Certified Mail & Patient Portal"""


def _generate_formal_dispute_letter(
    hospital_name: str,
    payer_name: str,
    audit_data: dict[str, Any],
    lang: str = "English",
) -> str:
    today_str = date.today().isoformat()
    audited_lines: list[AuditedLineItem] = audit_data["line_items"]
    charity_care: CharityCareSummary = audit_data["charity_care"]

    l1_lines = [
        line
        for line in audited_lines
        if line.status in ("NCCI_VIOLATION", "DUPLICATE", "REVENUE_CODE_ROLLUP")
    ]
    l2_lines = [line for line in audited_lines if line.status == "OVERCHARGED"]

    if lang == "Spanish":
        l1_section = (
            "\n".join(
                f"  * Línea {line.line_index + 1} — CPT {line.cpt_code} ({line.description}): "
                f"Facturado ${line.billed_amount:,.2f} -> DEDUCCIÓN EXIGIDA: -${line.layer_1_deduction:,.2f} [{line.status}]\n"
                f"    Base Legal: {line.citation}\n"
                f"    Motivo: {line.violation_reason}"
                for line in l1_lines
            )
            if l1_lines
            else "  * No se detectaron errores de codificación NCCI ni duplicados en Capa 1."
        )
        l2_section = (
            "\n".join(
                f"  * Línea {line.line_index + 1} — CPT {line.cpt_code} ({line.description}): "
                f"Facturado ${line.billed_amount:,.2f} vs Tarifa Negociada ${line.allowed_amount:,.2f} "
                f"(Base Medicare: ${line.medicare_rate:,.2f}) -> REDUCCIÓN EXIGIDA: -${line.layer_2_deduction:,.2f}\n"
                f"    Base Legal: {line.citation}\n"
                f"    Motivo: {line.violation_reason}"
                for line in l2_lines
            )
            if l2_lines
            else "  * Todos los procedimientos válidos se encuentran dentro de las tarifas negociadas publicadas."
        )
        return f"""FECHA: {today_str}

PARA: Servicios Financieros al Paciente, Departamento de Integridad de Ingresos y Cumplimiento
    {hospital_name}
    Ref: DISPUTA FORMAL DE AUDITORÍA MÉDICA Y APELACIÓN DE ASISTENCIA FINANCIERA ESTATUTARIA
    Aseguradora / Referencia de Plan: {payer_name}
    Monto Bruto Original Facturado: ${audit_data['total_billed']:,.2f}
    Saldo Legal Corregido a Pagar: ${audit_data['final_patient_balance']:,.2f} (Reducción Total Exigida: -${audit_data['total_savings']:,.2f})

Estimado Director de Integridad de Ingresos y Servicios Financieros:

Me dirijo a ustedes para disputar formalmente violaciones de codificación médica y sobreprecios de lista en mi estado de cuenta de {hospital_name}, y hacer valer mis derechos estatutarios de Asistencia Financiera según la ley federal y de California. Una auditoría determinística de 3 Capas identificó ${audit_data['total_savings']:,.2f} en cargos improcedentes o legalmente reducibles.

================================================================================
CAPA 1: VIOLACIONES DE DESGLOSE NCCI Y COBROS DUPLICADOS (-${audit_data['layer_1_coding_errors_removed']:,.2f})
================================================================================
Conforme al Manual de Políticas NCCI de CMS y las leyes contra facturación desleal, los siguientes cargos representan desglose indebido de servicios integrados o duplicación en la misma fecha de atención, por lo que deben eliminarse al 100%:
{l1_section}

================================================================================
CAPA 2: SOBREPRECIOS SOBRE TARIFAS NEGOCIADAS MRF (45 CFR PARTE 180) (-${audit_data['layer_2_mrf_overcharge_removed']:,.2f})
================================================================================
Conforme a la Regla Federal de Transparencia de Precios Hospitalarios (45 CFR § 180.50) y el Código IRS § 501(r)(5) (Montos Generalmente Facturados / AGB), un hospital exento de impuestos no puede cobrar tarifas brutas superiores a las tarifas negociadas publicadas para {payer_name}:
{l2_section}

  -> Subtotal Legal Válido tras Ajustes de Capa 1 y Capa 2: ${audit_data['subtotal_after_layer_2']:,.2f}

================================================================================
CAPA 3: ASISTENCIA FINANCIERA OBLIGATORIA / ATENCIÓN CARITATIVA (-${audit_data['layer_3_charity_care_forgiveness']:,.2f})
================================================================================
  * Tamaño del Hogar: {charity_care.household_size} personas
  * Ingreso Anual Bruto del Hogar: ${charity_care.annual_income:,.2f}
  * Nivel Federal de Pobreza (FPL) 2026: ${charity_care.fpl_base_2026:,.2f}
  * Porcentaje Verificado de FPL: {charity_care.user_fpl_pct:.1f}% FPL
  * Nivel Estatutario: {charity_care.tier_name}
  * Ley Aplicable: {charity_care.legal_citation}
  * Descuento Legal Obligatorio ({charity_care.discount_pct:.0f}% de ${audit_data['subtotal_after_layer_2']:,.2f}): -${audit_data['layer_3_charity_care_forgiveness']:,.2f}

================================================================================
RESUMEN DEL AJUSTE EXIGIDO DE LA CUENTA
================================================================================
  1. Monto Bruto Original Facturado:              ${audit_data['total_billed']:,.2f}
  2. Menos Errores de Codificación y NCCI:       -${audit_data['layer_1_coding_errors_removed']:,.2f}
  3. Menos Sobreprecio MRF para {payer_name}:    -${audit_data['layer_2_mrf_overcharge_removed']:,.2f}
  4. Subtotal Válido tras Auditoría:              ${audit_data['subtotal_after_layer_2']:,.2f}
  5. Menos Descuento Obligatorio de Asistencia ({charity_care.discount_pct:.0f}%): -${audit_data['layer_3_charity_care_forgiveness']:,.2f}
  ------------------------------------------------------------------------------
  SALDO FINAL JUSTO A PAGAR:                      ${audit_data['final_patient_balance']:,.2f}

Solicito la emisión de un estado de cuenta corregido que refleje el saldo debido de ${audit_data['final_patient_balance']:,.2f} en un plazo no mayor a 30 días, confirmando por escrito la suspensión inmediata de cualquier acción de cobro conforme a California Health & Safety Code § 127425 e IRS § 501(r)(6).

Atentamente,

[Firma del Paciente / Representante Autorizado]
Titular de la Cuenta — Enviado mediante Correo Certificado y Portal del Paciente"""

    if lang == "Vietnamese":
        l1_section = (
            "\n".join(
                f"  * Dòng {line.line_index + 1} — CPT {line.cpt_code} ({line.description}): "
                f"Tính ${line.billed_amount:,.2f} -> YÊU CẦU GIẢM: -${line.layer_1_deduction:,.2f} [{line.status}]\n"
                f"    Căn cứ pháp lý: {line.citation}\n"
                f"    Lý do: {line.violation_reason}"
                for line in l1_lines
            )
            if l1_lines
            else "  * Không phát hiện lỗi tách dịch vụ NCCI hay trùng lặp ở Lớp 1."
        )
        l2_section = (
            "\n".join(
                f"  * Dòng {line.line_index + 1} — CPT {line.cpt_code} ({line.description}): "
                f"Tính ${line.billed_amount:,.2f} vs Giá Thỏa thuận ${line.allowed_amount:,.2f} "
                f"(Mức chuẩn Medicare: ${line.medicare_rate:,.2f}) -> YÊU CẦU GIẢM: -${line.layer_2_deduction:,.2f}\n"
                f"    Căn cứ pháp lý: {line.citation}\n"
                f"    Lý do: {line.violation_reason}"
                for line in l2_lines
            )
            if l2_lines
            else "  * Tất cả dịch vụ hợp lệ đều nằm trong khung giá thỏa thuận công khai."
        )
        return f"""NGÀY: {today_str}

KÍNH GỬI: Ban Giám đốc Tuân thủ & Phòng Tài chính Bệnh nhân
    {hospital_name}
    V/v: KHIẾU NẠI CHÍNH THỨC KIỂM TOÁN HÓA ĐƠN & ĐỀ NGHỊ MIỄN GIẢM VIỆN PHÍ THEO LUẬT ĐỊNH
    Đơn vị Bảo hiểm / Chuẩn đối chiếu: {payer_name}
    Tổng số tiền Viện phí Ban đầu: ${audit_data['total_billed']:,.2f}
    Số dư Hợp pháp Cần thanh toán: ${audit_data['final_patient_balance']:,.2f} (Tổng số tiền yêu cầu giảm trừ: -${audit_data['total_savings']:,.2f})

Kính gửi Ban Giám đốc Tài chính & Tuân thủ:

Tôi viết thư này để chính thức khiếu nại các khoản tính phí sai quy định và vượt khung giá niêm yết trên hóa đơn của {hospital_name}, đồng thời yêu cầu áp dụng chính sách Hỗ trợ Viện phí theo quy định pháp luật. Kiểm toán độc lập 3 Lớp đã xác định ${audit_data['total_savings']:,.2f} là các khoản tính vượt mức hợp pháp.

================================================================================
LỚP 1: LỖI TÁCH DỊCH VỤ TRÁI PHÉP THEO CMS NCCI & TÍNH TRÙNG (-${audit_data['layer_1_coding_errors_removed']:,.2f})
================================================================================
{l1_section}

================================================================================
LỚP 2: TÍNH GIÁ VƯỢT MỨC NIÊM YẾT MRF (45 CFR PHẦN 180) (-${audit_data['layer_2_mrf_overcharge_removed']:,.2f})
================================================================================
{l2_section}

  -> Tạm tính hợp pháp sau Lớp 1 và Lớp 2: ${audit_data['subtotal_after_layer_2']:,.2f}

================================================================================
LỚP 3: MIỄN GIẢM THEO CHÍNH SÁCH HỖ TRỢ NGHÈO (CA AB 1020 & IRS § 501(r)) (-${audit_data['layer_3_charity_care_forgiveness']:,.2f})
================================================================================
  * Quy mô hộ gia đình: {charity_care.household_size} người
  * Thu nhập hàng năm: ${charity_care.annual_income:,.2f}
  * Chuẩn nghèo Liên bang FPL 2026: ${charity_care.fpl_base_2026:,.2f}
  * Tỷ lệ FPL thực tế: {charity_care.user_fpl_pct:.1f}% FPL
  * Mức miễn giảm bắt buộc ({charity_care.discount_pct:.0f}%): -${audit_data['layer_3_charity_care_forgiveness']:,.2f}

================================================================================
BẢNG TỔNG HỢP ĐIỀU CHỈNH TIỀN VIỆN PHÍ
================================================================================
  1. Tổng viện phí ban đầu:                      ${audit_data['total_billed']:,.2f}
  2. Trừ Lỗi mã hóa & Tách phí NCCI:            -${audit_data['layer_1_coding_errors_removed']:,.2f}
  3. Trừ Vượt giá thỏa thuận {payer_name}:      -${audit_data['layer_2_mrf_overcharge_removed']:,.2f}
  4. Tạm tính hợp pháp:                          ${audit_data['subtotal_after_layer_2']:,.2f}
  5. Trừ Miễn giảm theo luật Hỗ trợ Viện phí:   -${audit_data['layer_3_charity_care_forgiveness']:,.2f}
  ------------------------------------------------------------------------------
  SỐ TIỀN THỰC TẾ HỢP LÝ CẦN THANH TOÁN:         ${audit_data['final_patient_balance']:,.2f}

Yêu cầu bệnh viện phát hành hóa đơn mới với số tiền ${audit_data['final_patient_balance']:,.2f} trong vòng 30 ngày và tạm đình chỉ mọi hành vi thu hồi nợ theo luật California Health & Safety Code § 127425.

Trân trọng,

[Chữ ký Bệnh nhân / Người Đại diện]
Chủ tài khoản — Gửi qua Thư bảo đảm & Cổng thông tin Bệnh nhân"""

    if lang == "Russian":
        l1_section = (
            "\n".join(
                f"  * Строка {line.line_index + 1} — CPT {line.cpt_code} ({line.description}): "
                f"Начислено ${line.billed_amount:,.2f} -> ТРЕБУЕМЫЙ ВЫЧЕТ: -${line.layer_1_deduction:,.2f} [{line.status}]\n"
                f"    Правовое основание: {line.citation}\n"
                f"    Результат аудита: {line.violation_reason}"
                for line in l1_lines
            )
            if l1_lines
            else "  * Ошибок кодирования NCCI и повторных начислений не выявлено."
        )
        l2_section = (
            "\n".join(
                f"  * Строка {line.line_index + 1} — CPT {line.cpt_code} ({line.description}): "
                f"Начислено ${line.billed_amount:,.2f} vs Тариф ${line.allowed_amount:,.2f} "
                f"(База Medicare: ${line.medicare_rate:,.2f}) -> ТРЕБУЕМЫЙ ВЫЧЕТ: -${line.layer_2_deduction:,.2f}\n"
                f"    Правовое основание: {line.citation}\n"
                f"    Результат аудита: {line.violation_reason}"
                for line in l2_lines
            )
            if l2_lines
            else "  * Все подтвержденные процедуры укладываются в согласованные тарифы MRF."
        )
        return f"""ДАТА: {today_str}

КОМУ: Отдел финансовых расчетов с пациентами, комплаенса и аудита выручки
    {hospital_name}
    Тема: ОФИЦИАЛЬНАЯ ПРЕТЕНЗИЯ ПО РЕЗУЛЬТАТАМ АУДИТА МЕДИЦИНСКОГО СЧЕТА И ЗАЯВЛЕНИЕ НА ЛЬГОТУ
    Страховой план / Бенчмарк: {payer_name}
    Исходная сумма по прейскуранту: ${audit_data['total_billed']:,.2f}
    Законный скорректированный остаток к оплате: ${audit_data['final_patient_balance']:,.2f} (Сумма требуемого снижения: -${audit_data['total_savings']:,.2f})

Уважаемый руководитель финансового и комплаенс-отдела:

Настоящим заявляю официальную претензию относительно неправомерных начислений и завышения цен в моем счете от {hospital_name}, а также требую предоставить скидку по программе финансовой помощи в соответствии с федеральным законодательством и законами штата Калифорния. По итогам 3-уровневого аудита выявлено ${audit_data['total_savings']:,.2f} необоснованных начислений.

================================================================================
УРОВЕНЬ 1: НЕЗАКОННОЕ РАЗДЕЛЕНИЕ УСЛУГ (CMS NCCI) И ДУБЛИРУЮЩИЕ НАЧИСЛЕНИЯ (-${audit_data['layer_1_coding_errors_removed']:,.2f})
================================================================================
{l1_section}

================================================================================
УРОВЕНЬ 2: ПРЕВЫШЕНИЕ СОГЛАСОВАННЫХ ТАРИФОВ MRF (45 CFR PART 180) (-${audit_data['layer_2_mrf_overcharge_removed']:,.2f})
================================================================================
{l2_section}

  -> Законный промежуточный итог после уровней 1 и 2: ${audit_data['subtotal_after_layer_2']:,.2f}

================================================================================
УРОВЕНЬ 3: ОБЯЗАТЕЛЬНАЯ БЛАГОТВОРИТЕЛЬНАЯ ПОМОЩЬ (CA AB 1020 И IRS § 501(r)) (-${audit_data['layer_3_charity_care_forgiveness']:,.2f})
================================================================================
  * Состав семьи: {charity_care.household_size} чел.
  * Совокупный годовой доход: ${charity_care.annual_income:,.2f}
  * Порог бедности FPL 2026: ${charity_care.fpl_base_2026:,.2f}
  * Процент от FPL: {charity_care.user_fpl_pct:.1f}% FPL
  * Обязательная скидка ({charity_care.discount_pct:.0f}%): -${audit_data['layer_3_charity_care_forgiveness']:,.2f}

================================================================================
СВОДКА ТРЕБУЕМЫХ КОРРЕКТИРОВОК СЧЕТА
================================================================================
  1. Исходная сумма по счету:                     ${audit_data['total_billed']:,.2f}
  2. Минус Ошибки кодирования и правила NCCI:    -${audit_data['layer_1_coding_errors_removed']:,.2f}
  3. Минус Завышение тарифа для {payer_name}:     -${audit_data['layer_2_mrf_overcharge_removed']:,.2f}
  4. Проверенный промежуточный итог:              ${audit_data['subtotal_after_layer_2']:,.2f}
  5. Минус Обязательная благотворительная скидка: -${audit_data['layer_3_charity_care_forgiveness']:,.2f}
  ------------------------------------------------------------------------------
  ИТОГОВАЯ СПРАВЕДЛИВАЯ СУММА К ОПЛАТЕ:           ${audit_data['final_patient_balance']:,.2f}

Требую выставить исправленный счет на сумму ${audit_data['final_patient_balance']:,.2f} в течение 30 дней и письменно подтвердить приостановку всех процедур взыскания на основании California Health & Safety Code § 127425 и IRS § 501(r)(6).

С уважением,

[Подпись пациента / законного представителя]
Владелец счета — Направлено заказным письмом и через личный кабинет"""

    if l1_lines:
        l1_section = "\n".join(
            f"  * Line {line.line_index + 1} — CPT {line.cpt_code} ({line.description}): "
            f"Billed ${line.billed_amount:,.2f} -> DEMANDED DEDUCTION: -${line.layer_1_deduction:,.2f} "
            f"[{line.status}]\n"
            f"    Legal Authority: {line.citation}\n"
            f"    Audit Finding: {line.violation_reason}"
            for line in l1_lines
        )
    else:
        l1_section = "  * No Layer 1 NCCI unbundling or duplicate line items flagged."

    if l2_lines:
        l2_section = "\n".join(
            f"  * Line {line.line_index + 1} — CPT {line.cpt_code} ({line.description}): "
            f"Billed ${line.billed_amount:,.2f} vs. Allowed Rate ${line.allowed_amount:,.2f} "
            f"(Medicare Rate: ${line.medicare_rate:,.2f}) -> DEMANDED REDUCTION: -${line.layer_2_deduction:,.2f}\n"
            f"    Legal Authority: {line.citation}\n"
            f"    Audit Finding: {line.violation_reason}"
            for line in l2_lines
        )
    else:
        l2_section = "  * All valid CPT lines are within published MRF negotiated rates."

    return f"""DATE: {today_str}

TO: Patient Financial Services, Revenue Integrity & Compliance Department
    {hospital_name}
    Re: FORMAL MEDICAL BILL AUDIT DISPUTE & STATUTORY FINANCIAL ASSISTANCE APPEAL
    Insurance Payer / Plan Benchmark: {payer_name}
    Original Gross Amount Billed: ${audit_data['total_billed']:,.2f}
    Lawful Adjusted Patient Balance: ${audit_data['final_patient_balance']:,.2f} (Total Demanded Reduction: -${audit_data['total_savings']:,.2f})

Dear Revenue Integrity and Patient Financial Services Director:

I am writing to formally dispute specific coding violations and chargemaster overcharges on my itemized statement from {hospital_name}, and to assert my statutory Financial Assistance rights under federal and state law. A deterministic 3-Layer Audit of this account identified ${audit_data['total_savings']:,.2f} in unlawful or adjustable charges.

================================================================================
LAYER 1: CMS NCCI UNBUNDLING & DUPLICATE CODING VIOLATIONS (-${audit_data['layer_1_coding_errors_removed']:,.2f})
================================================================================
Pursuant to the CMS National Correct Coding Initiative (NCCI) Policy Manual and the False Claims Act / state unfair billing statutes, the following line items represent improper unbundling of integral supplies/venipuncture or duplicate billing on the same date of service and must be removed in full (100% adjustment):
{l1_section}

================================================================================
LAYER 2: 45 CFR PART 180 MRF NEGOTIATED RATE OVERCHARGES (-${audit_data['layer_2_mrf_overcharge_removed']:,.2f})
================================================================================
Pursuant to the federal Hospital Price Transparency Rule (45 CFR § 180.50) and Internal Revenue Code § 501(r)(5) (Amounts Generally Billed / AGB limitation), a tax-exempt hospital may not bill a patient gross chargemaster rates in excess of published payer-specific negotiated rates for {payer_name}. On the remaining valid procedures (excluding items already removed in Layer 1), {hospital_name} overcharged by ${audit_data['layer_2_mrf_overcharge_removed']:,.2f}:
{l2_section}

  -> Lawful Subtotal After Layer 1 & Layer 2 Adjustments: ${audit_data['subtotal_after_layer_2']:,.2f}

================================================================================
LAYER 3: MANDATORY CHARITY CARE / FINANCIAL ASSISTANCE (-${audit_data['layer_3_charity_care_forgiveness']:,.2f})
================================================================================
  * Household Size: {charity_care.household_size}
  * Gross Annual Household Income: ${charity_care.annual_income:,.2f}
  * 2026 Federal Poverty Level (FPL) Base: ${charity_care.fpl_base_2026:,.2f}
  * Verified Household FPL Percentage: {charity_care.user_fpl_pct:.1f}% FPL
  * Statutory Tier: {charity_care.tier_name}
  * Applicable Law: {charity_care.legal_citation}
  * Mandatory Charity Care Discount ({charity_care.discount_pct:.0f}% of ${audit_data['subtotal_after_layer_2']:,.2f}): -${audit_data['layer_3_charity_care_forgiveness']:,.2f}

================================================================================
SUMMARY OF DEMANDED ACCOUNT ADJUSTMENT
================================================================================
  1. Original Gross Billed Amount:                ${audit_data['total_billed']:,.2f}
  2. Less Layer 1 Coding & NCCI Errors Removed:  -${audit_data['layer_1_coding_errors_removed']:,.2f}
  3. Less Layer 2 {payer_name} MRF Overcharge:  -${audit_data['layer_2_mrf_overcharge_removed']:,.2f}
  4. Validated Allowed Subtotal:                  ${audit_data['subtotal_after_layer_2']:,.2f}
  5. Less Layer 3 Statutory Charity Care ({charity_care.discount_pct:.0f}%): -${audit_data['layer_3_charity_care_forgiveness']:,.2f}
  ------------------------------------------------------------------------------
  FINAL LAWFUL PATIENT BALANCE DUE:               ${audit_data['final_patient_balance']:,.2f}

Please issue a revised billing statement reflecting the corrected balance of ${audit_data['final_patient_balance']:,.2f} within thirty (30) days, and confirm in writing that all collection activity and credit reporting remain suspended pursuant to California Health & Safety Code § 127425 and IRS § 501(r)(6) pending resolution of this dispute.

Sincerely,

[Patient / Authorized Representative Signature]
Account Holder — Sent via Certified Mail & Patient Portal"""
