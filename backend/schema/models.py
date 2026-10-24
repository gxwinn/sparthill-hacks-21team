"""
backend/schema/models.py - Pydantic Data Models for Medical Bill Scanner & Savings Analyzer
"""

from typing import List, Dict, Any, Optional

try:
    from pydantic import BaseModel, Field
except ImportError:
    def Field(default=None, **kwargs):
        return default

    class BaseModel:
        def __init__(self, **kwargs):
            if "insurance company" in kwargs and "insurance_company" not in kwargs:
                kwargs["insurance_company"] = kwargs["insurance company"]
            for k, v in kwargs.items():
                setattr(self, k, v)

        def dict(self, *args, **kwargs):
            return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}


class PatientProcedureStated(BaseModel):
    name: Optional[str] = Field(None, description="Procedure name or service description (null if unclear)")
    code: Optional[str] = Field(None, description="Procedure billing code e.g. CPT or HCPCS (null if unclear)")
    statedPrice: Optional[float] = Field(None, description="Billed charge amount (null if unclear)")

    def __init__(self, **kwargs):
        self.name = kwargs.get("name")
        self.code = kwargs.get("code")
        self.statedPrice = kwargs.get("statedPrice")


class UserJson(BaseModel):
    """
    Format: {hospital, insurance company, patientProcedures: [{name, code, statedPrice}]}
    """
    hospital: Optional[str] = Field(None, description="Hospital or clinic name (null if unclear)")
    insurance_company: Optional[str] = Field(
        None,
        alias="insurance company",
        description="Patient's health insurance provider name (null if unclear)",
    )
    patientProcedures: List[PatientProcedureStated] = Field(
        default_factory=list,
        description="List of individual medical procedures with name, code, and stated price",
    )

    def __init__(self, **kwargs):
        self.hospital = kwargs.get("hospital")
        self.insurance_company = kwargs.get("insurance company") or kwargs.get("insurance_company")
        raw_procs = kwargs.get("patientProcedures", [])
        self.patientProcedures = [
            p if isinstance(p, PatientProcedureStated) else PatientProcedureStated(**p)
            for p in raw_procs
        ]

    class Config:
        populate_by_name = True

    def get_null_fields(self) -> List[str]:
        missing = []
        if not self.hospital:
            missing.append("hospital")
        if not self.insurance_company:
            missing.append("insurance company")
        for idx, proc in enumerate(self.patientProcedures):
            if proc.name is None:
                missing.append(f"procedure_{idx+1}_name")
            if proc.statedPrice is None:
                missing.append(f"procedure_{idx+1}_price")
        return missing

    def has_null_fields(self) -> bool:
        return len(self.get_null_fields()) > 0

    def to_user_dict(self) -> Dict[str, Any]:
        return {
            "hospital": self.hospital,
            "insurance company": self.insurance_company,
            "patientProcedures": [
                {
                    "name": proc.name,
                    "code": proc.code,
                    "statedPrice": proc.statedPrice,
                }
                for proc in self.patientProcedures
            ],
        }


InitialBillJson = UserJson


class ProcedurePriceDetail(BaseModel):
    code: Optional[str] = Field(None, description="CPT/HCPCS procedure code")
    initialPrice: float = Field(..., description="Initial stated price charged on patient bill")
    negotiatedPrice: float = Field(..., description="Negotiated contracted rate found in DuckDB database")

    def __init__(self, **kwargs):
        self.code = kwargs.get("code")
        self.initialPrice = float(kwargs.get("initialPrice", 0.0))
        self.negotiatedPrice = float(kwargs.get("negotiatedPrice", 0.0))


class FinalBillJson(BaseModel):
    hospital: str
    insurance_company: str = Field(..., alias="insurance company")
    initialTotalBill: float = Field(..., description="Sum of initial stated procedure charges")
    negotiatedFinalTotalBill: float = Field(
        ..., description="Sum of all negotiated prices found in DuckDB database"
    )
    finalTotalBill: Optional[float] = None
    procedureBreakdowns: Dict[str, ProcedurePriceDetail] = Field(default_factory=dict)

    def __init__(self, **kwargs):
        self.hospital = kwargs.get("hospital", "")
        self.insurance_company = kwargs.get("insurance company") or kwargs.get("insurance_company", "")
        self.initialTotalBill = float(kwargs.get("initialTotalBill", 0.0))
        self.negotiatedFinalTotalBill = float(kwargs.get("negotiatedFinalTotalBill", 0.0))
        self.finalTotalBill = float(kwargs.get("finalTotalBill", self.negotiatedFinalTotalBill))
        self.procedureBreakdowns = kwargs.get("procedureBreakdowns", {})

    class Config:
        populate_by_name = True
        extra = "allow"

    def to_output_dict(self) -> Dict[str, Any]:
        output: Dict[str, Any] = {
            "hospital": self.hospital,
            "insurance company": self.insurance_company,
            "initialTotalBill": round(self.initialTotalBill, 2),
            "negotiatedFinalTotalBill": round(self.negotiatedFinalTotalBill, 2),
            "finalTotalBill": round(self.finalTotalBill if self.finalTotalBill is not None else self.negotiatedFinalTotalBill, 2),
        }
        for proc_name, detail in self.procedureBreakdowns.items():
            output[proc_name] = {
                "code": detail.code,
                "initialPrice": round(detail.initialPrice, 2),
                "negotiatedPrice": round(detail.negotiatedPrice, 2),
            }
        return output
