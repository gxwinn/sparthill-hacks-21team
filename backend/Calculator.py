"""
Calculator.py - Medical Bill Discrepancy & Savings Calculator

Calls query.py to lookup DuckDB rates:
1. Receives userJson (with procedure codes and stated prices).
2. For each procedure, calls query.query_procedure (queries by code first, then by name).
3. If a procedure is matched by name instead of code, flags it for user confirmation.
4. Adds procedure code, initialPrice, and negotiatedPrice to finalbilljson (calculatedPrice removed).
5. Sums all negotiated prices into negotiatedFinalTotalBill.
6. Returns finalbilljson and any confirmation questions.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from typing import Dict, Any, Union, List, Tuple
from schema.models import UserJson, ProcedurePriceDetail, FinalBillJson
import query


def calculate_final_bill(
    user_json_input: Union[UserJson, Dict[str, Any]],
    user_confirmed_procedures: Dict[str, bool] = None,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Computes finalbilljson by calling query.py for each procedure under hospital & insurance.
    Returns (finalbilljson, pending_confirmations)
    """
    if isinstance(user_json_input, UserJson):
        user_json = user_json_input
    elif isinstance(user_json_input, dict):
        user_json = UserJson(**user_json_input)
    else:
        raise ValueError("Invalid userJson input passed to calculate_final_bill")

    hospital = user_json.hospital or "Unknown Hospital"
    insurance = user_json.insurance_company or "Self-Pay"
    user_confirmed_procedures = user_confirmed_procedures or {}

    initial_total = 0.0
    negotiated_final_total = 0.0
    procedure_breakdowns: Dict[str, ProcedurePriceDetail] = {}
    pending_confirmations: List[Dict[str, Any]] = []

    finalbilljson: Dict[str, Any] = {
        "hospital": hospital,
        "insurance company": insurance,
    }

    # Query DuckDB via query.py for each procedure under hospital & insurance
    for proc in user_json.patientProcedures:
        stated = float(proc.statedPrice or 0.0)
        initial_total += stated
        proc_name = proc.name or f"Procedure {proc.code or 'Unknown'}"

        # 2-stage query: query with code first, then if not found, with name
        match_result = query.query_procedure(
            hospital=hospital,
            insurance_company=insurance,
            procedure_code=proc.code,
            procedure_name=proc_name,
            stated_price=stated,
        )

        negotiated_price = float(match_result["negotiated_price"])
        effective_code = proc.code or match_result.get("matched_code")

        # Check if matched by name and user has not yet confirmed this specific item
        if match_result.get("needs_user_confirmation") and not user_confirmed_procedures.get(proc_name, False):
            pending_confirmations.append({
                "procedure_name": proc_name,
                "input_code": proc.code,
                "matched_name": match_result.get("matched_procedure_name"),
                "matched_code": match_result.get("matched_code"),
                "negotiated_price": negotiated_price,
                "question": match_result.get("confirmation_prompt") or f"Is '{match_result.get('matched_procedure_name')}' what you meant by '{proc_name}'?",
            })

        negotiated_final_total += negotiated_price

        # Record procedure detail with code, initialPrice, and negotiatedPrice (NO calculatedPrice)
        procedure_breakdowns[proc_name] = ProcedurePriceDetail(
            code=effective_code,
            initialPrice=round(stated, 2),
            negotiatedPrice=round(negotiated_price, 2),
        )

        finalbilljson[proc_name] = {
            "code": effective_code,
            "initialPrice": round(stated, 2),
            "negotiatedPrice": round(negotiated_price, 2),
        }

    # Sum all negotiated prices into negotiatedFinalTotalBill
    finalbilljson["initialTotalBill"] = round(initial_total, 2)
    finalbilljson["negotiatedFinalTotalBill"] = round(negotiated_final_total, 2)
    finalbilljson["finalTotalBill"] = round(negotiated_final_total, 2)

    return finalbilljson, pending_confirmations
