from typing import Literal
from pydantic import BaseModel, Field


class RawLineItem(BaseModel):
    cpt_code: str = Field(
        default="",
        description="5-digit CPT or HCPCS procedure code, or empty string if missing on a summary bill.",
    )
    description: str = Field(
        description="Hospital charge description for this service line."
    )
    quantity: int = Field(default=1, ge=1, description="Units or quantity billed.")
    billed_amount: float = Field(
        ge=0.0, description="Total gross dollar amount billed for this line item."
    )


class ExtractedBillSchema(BaseModel):
    hospital_name: str = Field(
        description="Hospital or medical center name extracted from the bill."
    )
    is_itemized: bool = Field(
        description="True if 5-digit CPT/HCPCS procedure codes are present; False if this is a summary statement without CPT codes."
    )
    line_items: list[RawLineItem] = Field(
        description="Extracted line items from the medical bill."
    )


class LineExplanationSchema(BaseModel):
    line_index: int = Field(description="Zero-based index of the line item on the bill.")
    cpt_code: str = Field(description="CPT code for this line item.")
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
    hospital_name: str = Field(default="El Camino Health")
    payer_name: str = Field(default="Anthem Blue Cross")
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


class GovernanceMetadata(BaseModel):
    pii_scrubbed_locally: bool = True
    phi_bytes_sent_to_cloud: int = 0
    redaction_method: str
    redacted_region: str
    redacted_fields: list[str]
    deterministic_sql_engine: str = (
        "DuckDB Embedded OLAP Engine (0% AI Math Hallucinations)"
    )
    ai_model_used: str = "gemini-2.5-flash"
    ai_mode: str
    sql_queries_executed: list[str]


class AuditReportResponse(BaseModel):
    audit_id: str
    timestamp: str
    hospital_name: str
    extracted_hospital_name: str
    payer_name: str
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
    governance: GovernanceMetadata
