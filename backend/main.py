"""
main.py - Medical Bill Error & Savings Scanner API

Orchestration endpoint coordinating:
1. Img = fastapi-fetch(imageinput)
2. userJson = pydantic(Gemini.py(imageinput))  # Model loaded from schema folder
3. hospitalbillinfo = hospitalinsurancedatabaseduckdb.py(userJson)
4. finalbilljson = Calculator.py(hospitalbillinfo, userJson)
5. return finalbilljson
"""

from typing import List, Dict, Any, Optional
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# ---------------------------------------------------------------------------
# Schema Imports (from schema folder)
# ---------------------------------------------------------------------------
try:
    from schema import (
        UserJson,
        PatientProcedureStated,
        PatientProcedureNegotiated,
        HospitalBillJson,
        ProcedurePriceDetail,
        FinalBillJson,
    )
except ImportError:
    from schema.models import (
        UserJson,
        PatientProcedureStated,
        PatientProcedureNegotiated,
        HospitalBillJson,
        ProcedurePriceDetail,
        FinalBillJson,
    )

# ---------------------------------------------------------------------------
# Pipeline Module Imports
# ---------------------------------------------------------------------------
import Gemini

# Separate modules saved for later implementation:
try:
    import hospitalinsurancedatabaseduckdb
except ImportError:
    hospitalinsurancedatabaseduckdb = None

try:
    import Calculator
except ImportError:
    Calculator = None


# ---------------------------------------------------------------------------
# FastAPI Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Medical Bill Scanner & Savings Analyzer API",
    description="Scans medical bills, extracts charges via Gemini, queries DuckDB rates, and calculates savings.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def health_check():
    return {
        "status": "online",
        "service": "Medical Bill Scanner & Savings Analyzer",
        "endpoints": ["/scan-bill"],
    }


@app.post("/scan-bill")
async def scan_medical_bill(imageinput: UploadFile = File(...)) -> Dict[str, Any]:
    """
    Orchestration Flow:
    1. Img = fastapi-fetch(imageinput)
    2. userJson = pydantic(Gemini.py(imageinput))
    3. hospitalbillinfo = hospitalinsurancedatabaseduckdb.py(userJson)
    4. finalbilljson = Calculator.py(hospitalbillinfo, userJson)
    5. return finalbilljson
    """
    if not imageinput.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Uploaded file must be an image (PNG, JPEG, WebP).")

    # 1. Img = fastapi-fetch(imageinput)
    Img = await imageinput.read()
    if not Img:
        raise HTTPException(status_code=400, detail="Empty image file received.")

    # 2. userJson = pydantic(Gemini.py(imageinput))
    # Gemini.py extracts data and validates via UserJson model in schema folder
    userJson: UserJson = Gemini.extract_bill_info(Img)

    # 3. hospitalbillinfo = hospitalinsurancedatabaseduckdb.py(userJson)
    if hospitalinsurancedatabaseduckdb and hasattr(hospitalinsurancedatabaseduckdb, "query_rates"):
        raw_hospital_dict = hospitalinsurancedatabaseduckdb.query_rates(userJson)
        hospitalbillinfo = HospitalBillJson(**raw_hospital_dict)
    else:
        # Simulated database response until hospitalinsurancedatabaseduckdb.py is implemented
        simulated_procedures = [
            PatientProcedureNegotiated(
                name=p.name,
                negotiatedPrice=round(p.statedPrice * 0.35, 2),
            )
            for p in userJson.patientProcedures
        ]
        hospitalbillinfo = HospitalBillJson(
            hospital=userJson.hospital,
            insuranceCompany=userJson.insurance_company,
            patientProcedures=simulated_procedures,
        )

    # 4. finalbilljson = Calculator.py(hospitalbillinfo, userJson)
    if Calculator and hasattr(Calculator, "calculate_final_bill"):
        finalbilljson = Calculator.calculate_final_bill(hospitalbillinfo, userJson)
    else:
        # Default calculation matching requested format
        initial_total = sum(p.statedPrice for p in userJson.patientProcedures)
        negotiated_lookup = {p.name: p.negotiatedPrice for p in hospitalbillinfo.patientProcedures}

        final_total = 0.0
        breakdowns: Dict[str, ProcedurePriceDetail] = {}

        for proc in userJson.patientProcedures:
            calc_price = negotiated_lookup.get(proc.name, proc.statedPrice)
            breakdowns[proc.name] = ProcedurePriceDetail(
                initialPrice=proc.statedPrice,
                calculatedPrice=calc_price,
            )
            final_total += calc_price

        bill_model = FinalBillJson(
            hospital=userJson.hospital,
            **{"insurance company": userJson.insurance_company},
            initialTotalBill=round(initial_total, 2),
            finalTotalBill=round(final_total, 2),
            procedureBreakdowns=breakdowns,
        )
        finalbilljson = bill_model.to_output_dict()

    # 5. return finalbilljson
    return finalbilljson


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
