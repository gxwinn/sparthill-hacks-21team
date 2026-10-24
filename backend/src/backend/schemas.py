from typing import Literal
from pydantic import BaseModel, Field


class RawLineItem(BaseModel):
    cpt_code: str = Field(
        default="",
        description="5-digit CPT/HCPCS procedure code, 4-digit UB-04 revenue code, or empty string if missing.",
    )
    description: str = Field(
        description="Hospital charge description for this service line."
    )
    quantity: int = Field(default=1, ge=1, description="Units or quantity billed.")
    billed_amount: float = Field(
        ge=0.0, description="Total gross dollar amount billed for this line item."
    )


class ExtractedBillSchema(BaseModel):
    is_valid_medical_document: bool = Field(
        default=True,
        description="True ONLY if the image is a genuine medical bill, hospital statement, Explanation of Benefits (EOB), or clinical discharge summary. False if the image is a landscape photo, random picture, non-medical receipt, or contains no healthcare billing/clinical content.",
    )
    rejection_reason: str = Field(
        default="",
        description="If is_valid_medical_document is False, a clear explanation of what the image appears to be and why it is not a medical billing document.",
    )
    hospital_name: str = Field(
        default="",
        description="Hospital or medical center name extracted from the bill (empty string if not visible).",
    )
    payer_name: str = Field(
        default="",
        description="Insurance payer or health plan name extracted from the bill (empty string if not visible).",
    )
    is_itemized: bool = Field(
        default=False,
        description="True if 5-digit CPT/HCPCS or 4-digit revenue codes are present; False if this is a summary statement without codes.",
    )
    line_items: list[RawLineItem] = Field(
        default_factory=list,
        description="Extracted billable procedure line items from the medical bill (empty list if not a medical bill).",
    )


class LineExplanationSchema(BaseModel):
    line_index: int = Field(description="Zero-based index of the line item on the bill.")
    cpt_code: str = Field(description="CPT or revenue code for this line item.")
    plain_language_meaning: str = Field(
        description="Plain-language explanation of what this medical procedure/code means in the user's selected language."
    )
    why_flagged: str = Field(
        description="Plain-language explanation in the user's selected language of why this line is valid or why the billing error is illegal."
    )


class AIExplanationResponse(BaseModel):
    overall_summary: str = Field(
        description="Plain-language executive summary of the 3-layer audit findings in the user's selected language."
    )
    line_explanations: list[LineExplanationSchema] = Field(
        description="Per-line plain-language translations and explanations in the user's selected language."
    )
    dispute_letter: str = Field(
        description="Formal, legally cited Dispute & Financial Assistance Appeal Letter (or HIPAA UB-04 Itemized Bill Request Letter) in English."
    )


class DemoAuditRequest(BaseModel):
    demo_id: str = Field(
        description="ID of the preset demo scenario (demo_1_er_trauma, demo_2_duplicate_labs, demo_3_summary_bill)."
    )
    hospital_name: str = Field(default="Auto-Detect from Bill")
    payer_name: str = Field(default="Auto-Detect from Bill")
    annual_income: float = Field(default=48000.0, ge=0.0)
    household_size: int = Field(default=3, ge=1)
    language: str = Field(default="English")


class AuditedLineItem(BaseModel):
    line_index: int
    cpt_code: str
    description: str
    quantity: int
    billed_amount: float
    allowed_amount: float
    medicare_rate: float
    layer_1_deduction: float
    layer_2_deduction: float
    patient_responsibility_before_charity: float
    status: Literal[
        "VALID",
        "NCCI_VIOLATION",
        "DUPLICATE",
        "REVENUE_CODE_ROLLUP",
        "OVERCHARGED",
        "MISSING_CPT",
    ]
    citation: str
    violation_reason: str
    plain_language_meaning: str = ""
    why_flagged: str = ""


class CharityCareSummary(BaseModel):
    annual_income: float
    household_size: int
    fpl_base_2026: float
    user_fpl_pct: float
    eligible: bool
    discount_pct: float
    forgiveness_amount: float
    tier_name: str
    legal_citation: str
    policy_explanation: str


class RedactedEntityBox(BaseModel):
    category: str = Field(
        description="PII category (e.g., Patient Name, SSN, Date of Birth, Phone Number, MRN / Account Number, Patient Address)."
    )
    bbox: list[int] = Field(
        description="Bounding box [x1, y1, x2, y2] in image pixels."
    )
    masked_label: str = Field(
        description="Redacted placeholder label (never exposes raw PHI)."
    )


class RedactionResponse(BaseModel):
    redaction_id: str = Field(
        description="Session ID referencing the locally cached sanitized image."
    )
    original_image_base64: str = Field(
        description="Base64 data URI of original image for local Step 1 preview."
    )
    redacted_image_base64: str = Field(
        description="Base64 data URI of surgically redacted image with solid black boxes over PII."
    )
    redacted_count: int = Field(
        description="Total number of sensitive PII entities surgically redacted."
    )
    detected_pii_categories: list[str] = Field(
        description="Distinct PII categories detected and scrubbed."
    )
    redacted_entities: list[RedactedEntityBox] = Field(
        default_factory=list,
        description="Bounding boxes and categories of each surgically redacted entity.",
    )
    whitelisted_items_preserved: int = Field(
        default=0,
        description="Number of medical procedure/CPT/charge/hospital tokens explicitly protected by whitelist.",
    )
    ocr_engine_used: str = Field(
        description="Offline local OCR engine used to extract word bounding boxes."
    )
    phi_bytes_sent_to_cloud: int = Field(
        default=0, description="Confirmed 0 bytes of PHI transmitted to cloud."
    )
    detected_hospital_name: str = Field(
        default="",
        description="Hospital/facility name auto-detected on the document during Stage 1 local OCR.",
    )
    detected_payer_name: str = Field(
        default="",
        description="Insurance payer name auto-detected on the document during Stage 1 local OCR.",
    )
    matched_local_hospital: str = Field(
        default="",
        description="Matched Bay Area MRF hospital name if in local registry, else empty string.",
    )
    matched_local_payer: str = Field(
        default="",
        description="Matched local MRF payer name if in local registry, else empty string.",
    )
    privacy_meta: dict = Field(
        default_factory=dict,
        description="Detailed governance metadata for downstream audit report.",
    )


class AnalyzeRedactedRequest(BaseModel):
    redaction_id: str = Field(
        default="", description="ID returned by /api/redact."
    )
    redacted_image_base64: str = Field(
        default="",
        description="Optional base64 data URI fallback of the already-redacted image.",
    )
    privacy_meta: dict = Field(
        default_factory=dict,
        description="Verification metadata from Stage 1 local redaction.",
    )
    hospital_name: str = Field(default="Auto-Detect from Bill")
    payer_name: str = Field(default="Auto-Detect from Bill")
    annual_income: float = Field(default=48000.0, ge=0.0)
    household_size: int = Field(default=3, ge=1)
    language: str = Field(default="English")


class SampleBillItem(BaseModel):
    filename: str
    label: str
    url: str
    suggested_hospital: str = "Auto-Detect from Bill"
    suggested_payer: str = "Auto-Detect from Bill"
    suggested_income: float = 48000.0
    suggested_household_size: int = 3


class GovernanceMetadata(BaseModel):
    pii_scrubbed_locally: bool = True
    phi_bytes_sent_to_cloud: int = 0
    redaction_method: str
    redacted_region: str
    redacted_fields: list[str]
    redacted_entity_count: int = 0
    detected_pii_categories: list[str] = Field(default_factory=list)
    whitelisted_medical_items_preserved: int = 0
    ocr_engine_used: str = "Offline Local OCR + Regex/Context Surgical Redactor"
    deterministic_sql_engine: str = (
        "DuckDB Embedded OLAP Engine (0% AI Math Hallucinations)"
    )
    ai_model_used: str = "gemini-3.5-flash-lite"
    ai_mode: str
    sql_queries_executed: list[str]
    data_provenance_sources: list[dict] = Field(default_factory=list)


class AuditReportResponse(BaseModel):
    audit_id: str
    timestamp: str
    hospital_name: str
    extracted_hospital_name: str
    payer_name: str
    extracted_payer_name: str = ""
    hospital_match_status: str = "MATCHED_LOCAL_MRF"
    payer_match_status: str = "MATCHED_LOCAL_MRF"
    pricing_benchmark_used: str = "LOCAL_MRF"
    detection_banner_message: str = ""
    language: str
    is_itemized: bool
    requires_ub04_request: bool
    total_billed: float
    layer_1_coding_errors_removed: float
    layer_2_mrf_overcharge_removed: float
    subtotal_after_layer_2: float
    layer_3_charity_care_forgiveness: float
    total_savings: float
    final_patient_balance: float
    charity_care: CharityCareSummary
    line_items: list[AuditedLineItem]
    plain_language_summary: str
    dispute_letter: str
    redacted_image_base64: str
    original_image_base64: str = ""
    governance: GovernanceMetadata


class TranslateAuditRequest(BaseModel):
    audit_report: AuditReportResponse
    language: str

