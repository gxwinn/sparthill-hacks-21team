"""
schema/models.py - Pydantic Data Models for Medical Bill Scanner & Savings Analyzer

Defines the three core data structures:
1. UserJson (Initial Bill): Extracted from bill image via Gemini.py
2. HospitalBillJson: Queried from DuckDB hospital rate database
3. FinalBillJson: Computed by Calculator.py comparing stated vs. negotiated pricing
"""

from typing import List, Dict, Any
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 1. Initial Bill / UserJson Schemas (Gemini extraction output)
# Format: {hospital, insurance company, patientProcedures: [{name, statedPrice}]}
# ---------------------------------------------------------------------------

class PatientProcedureStated(BaseModel):
    name: str = Field(..., description="Procedure name, description, or billing code")
    statedPrice: float = Field(..., description="Billed charge / stated price on patient bill")


class UserJson(BaseModel):
    """
    Format: {hospital, insurance company, patientProcedures: [{name, statedPrice}]}
    """
    hospital: str = Field(..., description="Hospital or healthcare provider name")
    insurance_company: str = Field(
        ...,
        alias="insurance company",
        description="Patient's health insurance provider name",
    )
    patientProcedures: List[PatientProcedureStated] = Field(
        default_factory=list,
        description="List of individual medical procedures with stated prices",
    )

    class Config:
        populate_by_name = True

    def to_user_dict(self) -> Dict[str, Any]:
        """Returns the dictionary formatted exactly matching the userJson specification."""
        return {
            "hospital": self.hospital,
            "insurance company": self.insurance_company,
            "patientProcedures": [
                {"name": proc.name, "statedPrice": proc.statedPrice}
                for proc in self.patientProcedures
            ],
        }


# Alias for backwards compatibility
InitialBillJson = UserJson


# ---------------------------------------------------------------------------
# 2. Hospital Bill Schemas (DuckDB query output)
# Format: {hospital, insuranceCompany, patientProcedures: [{name, negotiatedPrice}]}
# ---------------------------------------------------------------------------

class PatientProcedureNegotiated(BaseModel):
    name: str = Field(..., description="Procedure name or CPT/HCPCS code")
    negotiatedPrice: float = Field(
        ..., description="Negotiated contracted rate from hospital charge master database"
    )


class HospitalBillJson(BaseModel):
    """
    Format: {hospital, insuranceCompany, patientProcedures: [{name, negotiatedPrice}]}
    """
    hospital: str = Field(..., description="Hospital name")
    insuranceCompany: str = Field(..., description="Insurance company name")
    patientProcedures: List[PatientProcedureNegotiated] = Field(
        default_factory=list,
        description="List of procedures with their negotiated rates",
    )


# ---------------------------------------------------------------------------
# 3. Final Bill Schemas (Calculator output)
# Format: {
#   hospital,
#   insurance company,
#   initialTotalBill,
#   finalTotalBill,
#   procedurexName: {initialPrice, calculatedPrice},
#   procedureyName: {initialPrice, calculatedPrice}
# }
# ---------------------------------------------------------------------------

class ProcedurePriceDetail(BaseModel):
    initialPrice: float = Field(..., description="Initial price charged on patient bill")
    calculatedPrice: float = Field(..., description="Calculated/negotiated price")


class FinalBillJson(BaseModel):
    hospital: str
    insurance_company: str = Field(..., alias="insurance company")
    initialTotalBill: float
    finalTotalBill: float
    procedureBreakdowns: Dict[str, ProcedurePriceDetail] = Field(default_factory=dict)

    class Config:
        populate_by_name = True
        extra = "allow"

    def to_output_dict(self) -> Dict[str, Any]:
        """Flattens model into the exact requested JSON format with dynamic procedure keys."""
        output = {
            "hospital": self.hospital,
            "insurance company": self.insurance_company,
            "initialTotalBill": self.initialTotalBill,
            "finalTotalBill": self.finalTotalBill,
        }
        for proc_name, detail in self.procedureBreakdowns.items():
            output[proc_name] = {
                "initialPrice": detail.initialPrice,
                "calculatedPrice": detail.calculatedPrice,
            }
        return output
