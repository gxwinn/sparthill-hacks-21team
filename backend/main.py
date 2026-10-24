"""
main.py - Medical Bill Error & Savings Scanner API

Architecture & Endpoints:
1. loader.py is called at startup to load hospital insurance price JSONs from hospital subdirectories in database/.
2. /scan-bill: User uploads bill image. If any field is unclear, Gemini sets it to null.
   If null fields exist, prompts user to either re-upload or enter manually.
3. /manual-bill: Allows user to forgo uploading an image and fill in fields manually directly.
4. When querying DuckDB in Calculator.py:
   - Queries with code first.
   - If not found with code, queries with name and prompts the user to confirm if that is what the procedure meant.
5. Procedure code is included, and calculatedPrice & userinfo have been removed from finalbilljson.
"""

import sys
import os
# Ensure backend directory is in python search path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from typing import Dict, Any, List, Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware

# ---------------------------------------------------------------------------
# Pipeline Module Imports
# ---------------------------------------------------------------------------
import loader
import Gemini
import Calculator
import query
from schema import UserJson, PatientProcedureStated, FinalBillJson


# ---------------------------------------------------------------------------
# Lifespan: Load Hospital Subdirectory JSONs into DuckDB at start of main.py
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[main.py] Startup: calling loader.py to load hospital subdirectories into DuckDB...")
    rates_loaded = loader.load_hospital_database()
    print(f"[main.py] Ready. {rates_loaded} hospital rates active in DuckDB.")
    yield


app = FastAPI(
    title="Medical Bill Scanner & Savings Analyzer API",
    description="Loads hospital rate JSONs into DuckDB, scans bills or accepts manual entry, and validates procedure code/name matches.",
    version="4.0.0",
    lifespan=lifespan,
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
    total_rates = query.get_total_records_count()
    return {
        "status": "online",
        "service": "Medical Bill Scanner & Savings Analyzer",
        "duckdb_rates_loaded": total_rates,
        "endpoints": ["/scan-bill", "/manual-bill", "/complete-manual-entry", "/confirm-procedures"],
    }


@app.post("/scan-bill")
async def scan_medical_bill(imageinput: UploadFile = File(...)) -> Dict[str, Any]:
    """
    Scans an uploaded medical bill image:
    1. Extracts data via Gemini (unclear fields set to null).
    2. If null fields found, prompts user to re-upload or enter manually.
    3. Calls Calculator.py (code first, then name with confirmation).
    """
    if not imageinput.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Uploaded file must be an image (PNG, JPEG, WebP).")

    Img = await imageinput.read()
    if not Img:
        raise HTTPException(status_code=400, detail="Empty image file received.")

    # 1. Extract structured data with Gemini (unclear fields returned as null)
    userJson: UserJson = Gemini.extract_bill_info(Img)

    # 2. Check if any required field is null
    null_fields = userJson.get_null_fields()
    if null_fields:
        return {
            "status": "requires_manual_entry_or_reupload",
            "message": "Some fields could not be clearly read from the bill image. Please enter the missing fields manually or re-upload a clearer image.",
            "null_fields": null_fields,
            "userJson": userJson.to_user_dict(),
            "action_options": {
                "reupload": "Upload a sharper, well-lit photo of the bill",
                "manual_entry": "Fill in the missing values and submit to /manual-bill",
            },
        }

    # 3. Calculate final bill (checks code first, then name)
    finalbilljson, pending_confirmations = Calculator.calculate_final_bill(userJson)

    if pending_confirmations:
        return {
            "status": "requires_procedure_confirmation",
            "message": "Some procedures could not be matched by code, but matching procedures were found by name. Please confirm if these match.",
            "confirmations": pending_confirmations,
            "finalbilljson": finalbilljson,
            "userJson": userJson.to_user_dict(),
        }

    return {
        "status": "success",
        "finalbilljson": finalbilljson,
    }


@app.post("/manual-bill")
def manual_bill(manual_user_json: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """
    Allows the user to forgo uploading an image and instead submit their bill details manually.
    Accepts hospital, insurance company, and patientProcedures [{name, code, statedPrice}].
    """
    userJson = UserJson(**manual_user_json)
    null_fields = userJson.get_null_fields()
    if null_fields:
        raise HTTPException(status_code=422, detail=f"Please fill in all required fields: {null_fields}")

    finalbilljson, pending_confirmations = Calculator.calculate_final_bill(userJson)

    if pending_confirmations:
        return {
            "status": "requires_procedure_confirmation",
            "message": "Some procedures could not be matched by code, but matching procedures were found by name. Please confirm if these match.",
            "confirmations": pending_confirmations,
            "finalbilljson": finalbilljson,
            "userJson": userJson.to_user_dict(),
        }

    return {
        "status": "success",
        "finalbilljson": finalbilljson,
    }


@app.post("/confirm-procedures")
def confirm_procedures(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """
    Handles user confirmation for procedures matched by name.
    """
    raw_user_json = payload.get("userJson", {})
    confirmed_map = payload.get("confirmed_procedures", {})
    userJson = UserJson(**raw_user_json)

    finalbilljson, _ = Calculator.calculate_final_bill(
        user_json_input=userJson,
        user_confirmed_procedures=confirmed_map,
    )

    return {
        "status": "success",
        "finalbilljson": finalbilljson,
    }


if __name__ == "__main__":
    import uvicorn
    loader.load_hospital_database()
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
