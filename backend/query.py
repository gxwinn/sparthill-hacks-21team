"""
query.py - DuckDB Analytical Database Query Module

Handles all database connections and queries for hospital-payer negotiated rates:
1. Connects to in-process DuckDB database
2. Initializes schema for hospital_payer_rates
3. Inserts pricing records from JSON files loaded by loader.py
4. Query strategy:
   - First, query with the procedure code.
   - If not found with the code, query with the procedure name.
   - When matched by name instead of code, flags needs_user_confirmation=True
     so the system asks the user if that is what the procedure meant and to confirm.
5. In-memory fallback if DuckDB driver is not installed.
"""

from typing import List, Dict, Any, Optional
import re

try:
    import duckdb
except ImportError:
    duckdb = None

_DB_CONN = None
_MEMORY_FALLBACK_RATES: List[Dict[str, Any]] = []


def get_db_connection():
    """Returns or initializes the singleton in-process DuckDB database connection."""
    global _DB_CONN
    if _DB_CONN is not None:
        return _DB_CONN

    if duckdb is None:
        return None

    conn = duckdb.connect(database=":memory:")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS hospital_payer_rates (
            hospital VARCHAR,
            insurance_company VARCHAR,
            code VARCHAR,
            procedure_name VARCHAR,
            negotiated_price DOUBLE
        );
    """)

    _DB_CONN = conn
    return _DB_CONN


def insert_hospital_rates(records: List[Dict[str, Any]]) -> int:
    """Inserts a batch of hospital-insurance rate records into DuckDB and memory fallback."""
    conn = get_db_connection()
    if not records:
        return 0

    tuples_to_insert = []
    for item in records:
        rec = {
            "hospital": str(item.get("hospital", "")),
            "insurance_company": str(item.get("insurance_company", "")),
            "code": str(item.get("code", "")),
            "procedure_name": str(item.get("procedure_name", "")),
            "negotiated_price": float(item.get("negotiated_price", 0.0)),
        }
        tuples_to_insert.append((
            rec["hospital"],
            rec["insurance_company"],
            rec["code"],
            rec["procedure_name"],
            rec["negotiated_price"],
        ))
        _MEMORY_FALLBACK_RATES.append(rec)

    if conn is not None:
        conn.executemany("""
            INSERT INTO hospital_payer_rates VALUES (?, ?, ?, ?, ?);
        """, tuples_to_insert)

    return len(tuples_to_insert)


def query_procedure(
    hospital: Optional[str],
    insurance_company: Optional[str],
    procedure_code: Optional[str] = None,
    procedure_name: Optional[str] = None,
    stated_price: Optional[float] = 0.0,
) -> Dict[str, Any]:
    """
    Two-stage query strategy:
    1. First query with the code. If matched by code, no user confirmation needed.
    2. If not found by code, query with the procedure name.
       If matched by name, sets needs_user_confirmation=True to ask the user to confirm.
    3. Fallback to benchmark discount if neither matches.
    """
    safe_stated = float(stated_price or 0.0)
    if not hospital or not insurance_company:
        return {
            "negotiated_price": round(safe_stated * 0.35, 2),
            "matched_by": "benchmark",
            "matched_code": procedure_code,
            "matched_procedure_name": procedure_name,
            "needs_user_confirmation": False,
        }

    conn = get_db_connection()
    h_clean = hospital.strip().lower()
    ins_clean = insurance_company.strip().lower()

    # ---------------------------------------------------------
    # STAGE 1: Query with the CODE first
    # ---------------------------------------------------------
    if procedure_code and procedure_code.strip():
        code_clean = procedure_code.strip()

        # DuckDB query
        if conn is not None:
            row = conn.execute("""
                SELECT negotiated_price, procedure_name, code
                FROM hospital_payer_rates 
                WHERE LOWER(hospital) = LOWER(?)
                  AND LOWER(insurance_company) = LOWER(?)
                  AND LOWER(code) = LOWER(?)
                LIMIT 1;
            """, [hospital.strip(), insurance_company.strip(), code_clean]).fetchone()

            if row:
                return {
                    "negotiated_price": float(row[0]),
                    "matched_by": "code",
                    "matched_code": str(row[2]),
                    "matched_procedure_name": str(row[1]),
                    "needs_user_confirmation": False,
                }

        # Memory fallback search for code
        for r in _MEMORY_FALLBACK_RATES:
            if (r["hospital"].lower() == h_clean or h_clean in r["hospital"].lower()) and \
               (r["insurance_company"].lower() == ins_clean or ins_clean in r["insurance_company"].lower()):
                if r["code"].lower() == code_clean.lower():
                    return {
                        "negotiated_price": float(r["negotiated_price"]),
                        "matched_by": "code",
                        "matched_code": r["code"],
                        "matched_procedure_name": r["procedure_name"],
                        "needs_user_confirmation": False,
                    }

    # ---------------------------------------------------------
    # STAGE 2: If not found with the code, query with the NAME
    # ---------------------------------------------------------
    if procedure_name and procedure_name.strip():
        proc_clean = procedure_name.strip()

        # Check DuckDB by name (exact or partial)
        if conn is not None:
            # 2a. Exact name match
            row = conn.execute("""
                SELECT negotiated_price, procedure_name, code
                FROM hospital_payer_rates 
                WHERE LOWER(hospital) = LOWER(?)
                  AND LOWER(insurance_company) = LOWER(?)
                  AND LOWER(procedure_name) = LOWER(?)
                LIMIT 1;
            """, [hospital.strip(), insurance_company.strip(), proc_clean]).fetchone()

            if row:
                return {
                    "negotiated_price": float(row[0]),
                    "matched_by": "name",
                    "matched_code": str(row[2]),
                    "matched_procedure_name": str(row[1]),
                    "needs_user_confirmation": True,
                    "confirmation_prompt": f"Is '{row[1]}' (Code: {row[2]}) what '{proc_clean}' meant?",
                }

            # 2b. Keyword / partial LIKE search by name
            row = conn.execute("""
                SELECT negotiated_price, procedure_name, code
                FROM hospital_payer_rates 
                WHERE LOWER(hospital) = LOWER(?)
                  AND LOWER(insurance_company) = LOWER(?)
                  AND (LOWER(?) LIKE '%' || LOWER(procedure_name) || '%' 
                       OR LOWER(procedure_name) LIKE '%' || LOWER(?) || '%')
                LIMIT 1;
            """, [hospital.strip(), insurance_company.strip(), proc_clean, proc_clean]).fetchone()

            if row:
                return {
                    "negotiated_price": float(row[0]),
                    "matched_by": "name",
                    "matched_code": str(row[2]),
                    "matched_procedure_name": str(row[1]),
                    "needs_user_confirmation": True,
                    "confirmation_prompt": f"Is '{row[1]}' (Code: {row[2]}) what '{proc_clean}' meant?",
                }

        # Memory fallback search for name
        for r in _MEMORY_FALLBACK_RATES:
            if (r["hospital"].lower() == h_clean or h_clean in r["hospital"].lower()) and \
               (r["insurance_company"].lower() == ins_clean or ins_clean in r["insurance_company"].lower()):
                if r["procedure_name"].lower() == proc_clean.lower() or \
                   proc_clean.lower() in r["procedure_name"].lower() or \
                   r["procedure_name"].lower() in proc_clean.lower():
                    return {
                        "negotiated_price": float(r["negotiated_price"]),
                        "matched_by": "name",
                        "matched_code": r["code"],
                        "matched_procedure_name": r["procedure_name"],
                        "needs_user_confirmation": True,
                        "confirmation_prompt": f"Is '{r['procedure_name']}' (Code: {r['code']}) what '{proc_clean}' meant?",
                    }

    # ---------------------------------------------------------
    # STAGE 3: Default benchmark discount
    # ---------------------------------------------------------
    return {
        "negotiated_price": round(safe_stated * 0.35, 2),
        "matched_by": "benchmark",
        "matched_code": procedure_code,
        "matched_procedure_name": procedure_name,
        "needs_user_confirmation": False,
    }


def query_negotiated_rate(
    hospital: Optional[str],
    insurance_company: Optional[str],
    procedure_name: Optional[str],
    procedure_code: Optional[str] = None,
    stated_price: Optional[float] = 0.0,
) -> float:
    """Helper returning just the float price from query_procedure."""
    res = query_procedure(
        hospital=hospital,
        insurance_company=insurance_company,
        procedure_code=procedure_code,
        procedure_name=procedure_name,
        stated_price=stated_price,
    )
    return float(res["negotiated_price"])


def get_total_records_count() -> int:
    conn = get_db_connection()
    if conn is not None:
        row = conn.execute("SELECT COUNT(*) FROM hospital_payer_rates;").fetchone()
        if row:
            return int(row[0])
    return len(_MEMORY_FALLBACK_RATES)
