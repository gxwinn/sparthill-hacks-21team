from datetime import date
import json
from typing import Any
from google import genai
from google.genai import types
from backend.config import settings
from backend.demo_data import DEMO_BILLS
from backend.schemas import (
    AIExplanationResponse,
    AuditedLineItem,
    CharityCareSummary,
    ExtractedBillSchema,
    LineExplanationSchema,
    RawLineItem,
)

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
}


def _has_valid_api_key() -> bool:
    key = (settings.GEMINI_API_KEY or "").strip()
    return bool(key) and key != "your_gemini_api_key_here"


def extract_bill_from_image(
    redacted_image_bytes: bytes,
    mime_type: str = "image/png",
    fallback_hospital: str = "El Camino Health",
) -> tuple[ExtractedBillSchema, str]:
    """
    Step 2: Use google-genai (`gemini-2.5-flash`) with Structured Outputs (`response_schema`)
    to extract structured line items from the PII-redacted medical bill image.
    """
    if _has_valid_api_key():
        try:
            client = genai.Client(api_key=settings.GEMINI_API_KEY)
            prompt = (
                "You are an expert medical billing auditor OCR system. "
                "Examine this PII-redacted medical bill image (the top 15% header was blacked out locally for HIPAA privacy). "
                "Extract the hospital_name, determine is_itemized (True ONLY if 5-character CPT/HCPCS codes are present, "
                "False if this is a consolidated summary bill without CPT codes), and extract all line_items "
                "with cpt_code, description, quantity, and billed_amount."
            )
            response = client.models.generate_content(
                model=settings.GEMINI_MODEL,
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
            if response.parsed and isinstance(response.parsed, ExtractedBillSchema):
                parsed_bill: ExtractedBillSchema = response.parsed
                if parsed_bill.line_items:
                    return (
                        parsed_bill,
                        f"Live Google GenAI SDK ({settings.GEMINI_MODEL} Vision Structured Output)",
                    )
            if response.text:
                data = json.loads(response.text)
                parsed_bill = ExtractedBillSchema(**data)
                if parsed_bill.line_items:
                    return (
                        parsed_bill,
                        f"Live Google GenAI SDK ({settings.GEMINI_MODEL} Vision JSON)",
                    )
        except Exception as exc:
            fallback_reason = f"Deterministic Fallback (Gemini OCR fallback triggered: {type(exc).__name__})"
        else:
            fallback_reason = "Deterministic Fallback (Uploaded synthetic/blank test image -> loaded ER Trauma template)"
    else:
        fallback_reason = (
            "Deterministic Offline Mode (Set GEMINI_API_KEY in .env for live gemini-2.5-flash Vision OCR)"
        )

    demo_default = DEMO_BILLS["demo_1_er_trauma"]
    return (
        ExtractedBillSchema(
            hospital_name=fallback_hospital or demo_default["hospital_name"],
            is_itemized=True,
            line_items=[RawLineItem(**item) for item in demo_default["line_items"]],
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
    Step 4: Use google-genai (`gemini-2.5-flash`) with Structured Outputs (`response_schema`)
    to generate:
      1. Plain-language summary & per-CPT explanations in the user's requested language.
      2. A formal, legally cited Dispute & Financial Assistance Appeal Letter in English.
    """
    audited_lines: list[AuditedLineItem] = audit_data["line_items"]
    charity_care: CharityCareSummary = audit_data["charity_care"]
    is_itemized: bool = audit_data["is_itemized"]

    if _has_valid_api_key():
        try:
            client = genai.Client(api_key=settings.GEMINI_API_KEY)
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
                f"3. `dispute_letter`: A formal, ready-to-send letter in English addressed to {hospital_name} "
                f"Patient Financial Services & Billing Compliance Department. "
                f"If `is_itemized` is False, write a formal 'HIPAA Itemized Bill (Form CMS-1450 / UB-04) Request Letter' "
                f"citing 45 CFR § 164.524 and demanding a halt to billing collections until CPT/HCPCS codes are supplied. "
                f"If `is_itemized` is True, write a formal 'Medical Bill Dispute & Financial Assistance Appeal Letter' "
                f"citing the exact CPT codes, CMS NCCI edit violations, 45 CFR Part 180 Hospital Price Transparency MRF "
                f"negotiated rates for {payer_name}, and California AB 1020 / IRS § 501(r) charity care calculations."
            )

            response = client.models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=[prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=AIExplanationResponse,
                    temperature=0.1,
                ),
            )
            if response.parsed and isinstance(response.parsed, AIExplanationResponse):
                return (
                    response.parsed,
                    f"Live Google GenAI SDK ({settings.GEMINI_MODEL} Structured Output)",
                )
            if response.text:
                data = json.loads(response.text)
                return (
                    AIExplanationResponse(**data),
                    f"Live Google GenAI SDK ({settings.GEMINI_MODEL} JSON)",
                )
        except Exception as exc:
            mode_label = f"Deterministic Multi-Language Engine (Gemini fallback: {type(exc).__name__})"
        else:
            mode_label = "Deterministic Multi-Language Engine"
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
        )
    else:
        dispute_letter = _generate_formal_dispute_letter(
            hospital_name=hospital_name,
            payer_name=payer_name,
            audit_data=audit_data,
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
) -> str:
    today_str = date.today().isoformat()
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
) -> str:
    today_str = date.today().isoformat()
    audited_lines: list[AuditedLineItem] = audit_data["line_items"]
    charity_care: CharityCareSummary = audit_data["charity_care"]

    l1_lines = [
        line for line in audited_lines if line.status in ("NCCI_VIOLATION", "DUPLICATE")
    ]
    l2_lines = [line for line in audited_lines if line.status == "OVERCHARGED"]

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
