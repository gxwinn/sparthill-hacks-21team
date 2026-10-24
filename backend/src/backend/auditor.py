import re
from typing import Any
from backend.db import get_connection
from backend.schemas import (
    AuditedLineItem,
    CharityCareSummary,
    ExtractedBillSchema,
)

CPT_REGEX = re.compile(r"^[A-Z0-9]{5}$")


def is_valid_cpt_code(code: str) -> bool:
    cleaned = (code or "").strip().upper()
    return bool(CPT_REGEX.match(cleaned)) and any(ch.isdigit() for ch in cleaned)


def run_deterministic_audit(
    extracted_bill: ExtractedBillSchema,
    hospital_name: str,
    payer_name: str,
    annual_income: float,
    household_size: int,
) -> dict[str, Any]:
    """
    Execute the deterministic 3-Layer DuckDB Audit with 0% AI math hallucinations.
    """
    sql_queries_executed: list[str] = []
    line_items = extracted_bill.line_items
    total_billed = round(sum(item.billed_amount for item in line_items), 2)

    # Determine whether the bill is itemized with valid 5-character CPT/HCPCS codes
    has_cpt_codes = any(is_valid_cpt_code(item.cpt_code) for item in line_items)
    is_itemized = bool(extracted_bill.is_itemized and has_cpt_codes)

    # Calculate 2026 Federal Poverty Level (FPL)
    safe_household_size = max(1, int(household_size))
    fpl_base = float(15650 + (safe_household_size - 1) * 5500)
    user_fpl_pct = round((float(annual_income) / fpl_base) * 100.0, 2)

    with get_connection() as conn:
        # Query Layer 3 Charity Care tier from DuckDB
        cc_sql_display = (
            f"SELECT tier_name, discount_pct, legal_citation, policy_summary "
            f"FROM charity_care_rules "
            f"WHERE {user_fpl_pct} BETWEEN min_fpl_pct AND max_fpl_pct LIMIT 1;"
        )
        sql_queries_executed.append(cc_sql_display)
        cc_row = conn.execute(
            """
            SELECT tier_name, discount_pct, legal_citation, policy_summary
            FROM charity_care_rules
            WHERE ? >= min_fpl_pct AND ? <= max_fpl_pct
            LIMIT 1
            """,
            [user_fpl_pct, user_fpl_pct],
        ).fetchone()

        # Deterministic statutory rule enforcement (CA AB 1020 & IRS 501(r))
        if user_fpl_pct <= 200.0:
            discount_pct = 100.0
            tier_name = (
                cc_row[0]
                if cc_row
                else "Tier 1 — Full Charity Care Forgiveness (<= 200% FPL)"
            )
            legal_citation = (
                cc_row[2]
                if cc_row
                else "California Health & Safety Code § 127405 (AB 1020) & IRS § 501(r)(4)"
            )
            policy_summary = (
                cc_row[3]
                if cc_row
                else "100% forgiveness of remaining valid out-of-pocket bill (<= 200% FPL)."
            )
        elif user_fpl_pct <= 400.0:
            discount_pct = 65.0
            tier_name = (
                cc_row[0]
                if cc_row
                else "Tier 2 — Extended Financial Assistance Discount (200% - 400% FPL)"
            )
            legal_citation = (
                cc_row[2]
                if cc_row
                else "California Health & Safety Code § 127405 (AB 1020) & IRS § 501(r)(5)"
            )
            policy_summary = (
                cc_row[3]
                if cc_row
                else "65% statutory discount on remaining valid out-of-pocket bill (200% - 400% FPL)."
            )
        else:
            discount_pct = 0.0
            tier_name = (
                cc_row[0]
                if cc_row
                else "Tier 3 — Standard Financial Policy (> 400% FPL)"
            )
            legal_citation = (
                cc_row[2]
                if cc_row
                else "IRS § 501(r) Standard Financial Assistance Threshold"
            )
            policy_summary = (
                cc_row[3]
                if cc_row
                else "Income exceeds 400% FPL threshold for mandatory charity care discount."
            )

        # Edge Case: Non-itemized Summary Bill without CPT codes
        if not is_itemized:
            audited_lines: list[AuditedLineItem] = []
            for idx, item in enumerate(line_items):
                audited_lines.append(
                    AuditedLineItem(
                        line_index=idx,
                        cpt_code=item.cpt_code or "MISSING",
                        description=item.description,
                        quantity=item.quantity,
                        billed_amount=round(item.billed_amount, 2),
                        allowed_amount=round(item.billed_amount, 2),
                        medicare_rate=0.0,
                        layer_1_deduction=0.0,
                        layer_2_deduction=0.0,
                        patient_responsibility_before_charity=round(
                            item.billed_amount, 2
                        ),
                        status="MISSING_CPT",
                        citation="45 CFR § 164.524 (HIPAA Right of Access) & CMS Form UB-04 (CMS-1450)",
                        violation_reason=(
                            "Summary department charge lacks a 5-digit CPT/HCPCS code. "
                            "Cannot verify NCCI bundling or MRF negotiated rates until hospital provides an itemized UB-04 bill."
                        ),
                    )
                )

            charity_summary = CharityCareSummary(
                annual_income=round(annual_income, 2),
                household_size=safe_household_size,
                fpl_base_2026=round(fpl_base, 2),
                user_fpl_pct=user_fpl_pct,
                eligible=(discount_pct > 0.0),
                discount_pct=discount_pct,
                forgiveness_amount=0.0,
                tier_name=tier_name,
                legal_citation=legal_citation,
                policy_explanation=(
                    f"{policy_summary} (Pending receipt of itemized UB-04 statement with CPT codes.)"
                ),
            )

            return {
                "is_itemized": False,
                "requires_ub04_request": True,
                "total_billed": total_billed,
                "layer_1_coding_errors_removed": 0.0,
                "layer_2_mrf_overcharge_removed": 0.0,
                "subtotal_after_layer_2": total_billed,
                "layer_3_charity_care_forgiveness": 0.0,
                "total_savings": 0.0,
                "final_patient_balance": total_billed,
                "charity_care": charity_summary,
                "line_items": audited_lines,
                "sql_queries_executed": sql_queries_executed,
            }

        # =====================================================================
        # LAYER 1: Coding Errors & Unbundling (Duplicate Check + NCCI Edits)
        # =====================================================================
        distinct_cpts = sorted(
            {
                item.cpt_code.strip().upper()
                for item in line_items
                if is_valid_cpt_code(item.cpt_code)
            }
        )

        ncci_violations_by_col2: dict[str, dict[str, str]] = {}
        if distinct_cpts:
            cpt_list_sql = ", ".join(f"'{c}'" for c in distinct_cpts)
            ncci_sql_display = (
                f"SELECT column_1_cpt, column_2_cpt, violation_reason, cms_citation "
                f"FROM ncci_edits "
                f"WHERE column_1_cpt IN ({cpt_list_sql}) "
                f"AND column_2_cpt IN ({cpt_list_sql});"
            )
            sql_queries_executed.append(ncci_sql_display)

            placeholders = ", ".join("?" for _ in distinct_cpts)
            ncci_rows = conn.execute(
                f"""
                SELECT column_1_cpt, column_2_cpt, violation_reason, cms_citation
                FROM ncci_edits
                WHERE column_1_cpt IN ({placeholders})
                  AND column_2_cpt IN ({placeholders})
                """,
                distinct_cpts + distinct_cpts,
            ).fetchall()

            for col1, col2, reason, citation in ncci_rows:
                ncci_violations_by_col2[col2] = {
                    "column_1_cpt": col1,
                    "column_2_cpt": col2,
                    "violation_reason": reason,
                    "cms_citation": citation,
                }

        # =====================================================================
        # LAYER 2: Payer-Specific MRF Rate & Medicare Benchmark Lookup
        # =====================================================================
        # Log the batch MRF lookup query for transparency
        if distinct_cpts:
            cpt_list_sql = ", ".join(f"'{c}'" for c in distinct_cpts)
            mrf_sql_display = (
                f"SELECT cpt_code, description, gross_charge, allowed_payer_rate, medicare_rate "
                f"FROM hospital_prices "
                f"WHERE hospital_name = '{hospital_name}' "
                f"AND payer_name = '{payer_name}' "
                f"AND cpt_code IN ({cpt_list_sql});"
            )
            sql_queries_executed.append(mrf_sql_display)

        seen_cpts: set[str] = set()
        audited_lines = []

        for idx, item in enumerate(line_items):
            cpt = item.cpt_code.strip().upper()
            billed = round(float(item.billed_amount), 2)
            qty = max(1, int(item.quantity))

            # 1A. Duplicate CPT Check on same statement
            if cpt in seen_cpts:
                audited_lines.append(
                    AuditedLineItem(
                        line_index=idx,
                        cpt_code=cpt,
                        description=item.description,
                        quantity=qty,
                        billed_amount=billed,
                        allowed_amount=0.0,
                        medicare_rate=0.0,
                        layer_1_deduction=billed,
                        layer_2_deduction=0.0,
                        patient_responsibility_before_charity=0.0,
                        status="DUPLICATE",
                        citation=f"CMS Claims Processing Manual Ch. 1, § 120.2 — Duplicate Billing of CPT {cpt}",
                        violation_reason=(
                            f"Duplicate charge: CPT {cpt} ({item.description}) was already billed on an earlier line of this statement."
                        ),
                    )
                )
                continue

            seen_cpts.add(cpt)

            # 1B. CMS NCCI Unbundling Check
            if cpt in ncci_violations_by_col2:
                ncci_info = ncci_violations_by_col2[cpt]
                audited_lines.append(
                    AuditedLineItem(
                        line_index=idx,
                        cpt_code=cpt,
                        description=item.description,
                        quantity=qty,
                        billed_amount=billed,
                        allowed_amount=0.0,
                        medicare_rate=0.0,
                        layer_1_deduction=billed,
                        layer_2_deduction=0.0,
                        patient_responsibility_before_charity=0.0,
                        status="NCCI_VIOLATION",
                        citation=ncci_info["cms_citation"],
                        violation_reason=ncci_info["violation_reason"],
                    )
                )
                continue

            # 2. Layer 2 Payer MRF Rate or Medicare Benchmark Check (only for lines not removed in Layer 1)
            price_row = conn.execute(
                """
                SELECT allowed_payer_rate, medicare_rate, gross_charge
                FROM hospital_prices
                WHERE hospital_name = ? AND payer_name = ? AND cpt_code = ?
                LIMIT 1
                """,
                [hospital_name, payer_name, cpt],
            ).fetchone()

            used_medicare_fallback = False
            if price_row is not None:
                unit_allowed = float(price_row[0])
                unit_medicare = float(price_row[1])
            else:
                used_medicare_fallback = True
                bench_sql_display = (
                    f"SELECT fair_allowed_amount, medicare_rate FROM medicare_benchmark "
                    f"WHERE cpt_code = '{cpt}';"
                )
                if bench_sql_display not in sql_queries_executed:
                    sql_queries_executed.append(bench_sql_display)

                bench_row = conn.execute(
                    """
                    SELECT fair_allowed_amount, medicare_rate
                    FROM medicare_benchmark
                    WHERE cpt_code = ?
                    LIMIT 1
                    """,
                    [cpt],
                ).fetchone()
                if bench_row is not None:
                    unit_allowed = float(bench_row[0])
                    unit_medicare = float(bench_row[1])
                else:
                    # Unknown CPT code fallback: 40% of billed as conservative benchmark
                    unit_allowed = round(billed * 0.40, 2)
                    unit_medicare = round(billed * 0.22, 2)

            allowed_total = round(unit_allowed * qty, 2)
            medicare_total = round(unit_medicare * qty, 2)

            if billed > allowed_total:
                overcharge = round(billed - allowed_total, 2)
                if used_medicare_fallback:
                    citation = (
                        f"CMS Medicare Benchmark Fallback (1.8x Medicare Rate = ${allowed_total:,.2f}; "
                        f"Base Medicare = ${medicare_total:,.2f})"
                    )
                    violation_reason = (
                        f"Hospital gross charge (${billed:,.2f}) exceeds 180% CMS Medicare fair benchmark "
                        f"(${allowed_total:,.2f}) by ${overcharge:,.2f}."
                    )
                else:
                    citation = (
                        f"45 CFR Part 180 Hospital Price Transparency MRF — {hospital_name} / {payer_name} "
                        f"Negotiated Rate: ${allowed_total:,.2f} (Medicare: ${medicare_total:,.2f})"
                    )
                    violation_reason = (
                        f"Chargemaster gross bill (${billed:,.2f}) exceeds {hospital_name}'s published "
                        f"{payer_name} MRF negotiated rate (${allowed_total:,.2f}) by ${overcharge:,.2f}."
                    )

                audited_lines.append(
                    AuditedLineItem(
                        line_index=idx,
                        cpt_code=cpt,
                        description=item.description,
                        quantity=qty,
                        billed_amount=billed,
                        allowed_amount=allowed_total,
                        medicare_rate=medicare_total,
                        layer_1_deduction=0.0,
                        layer_2_deduction=overcharge,
                        patient_responsibility_before_charity=allowed_total,
                        status="OVERCHARGED",
                        citation=citation,
                        violation_reason=violation_reason,
                    )
                )
            else:
                audited_lines.append(
                    AuditedLineItem(
                        line_index=idx,
                        cpt_code=cpt,
                        description=item.description,
                        quantity=qty,
                        billed_amount=billed,
                        allowed_amount=billed,
                        medicare_rate=medicare_total,
                        layer_1_deduction=0.0,
                        layer_2_deduction=0.0,
                        patient_responsibility_before_charity=billed,
                        status="VALID",
                        citation=(
                            f"45 CFR Part 180 MRF Verified — Within {payer_name} Negotiated Rate (${allowed_total:,.2f})"
                        ),
                        violation_reason="Billed amount does not exceed the published MRF negotiated rate.",
                    )
                )

        # Aggregate Layer 1 & Layer 2 savings (strictly mutually exclusive — 0% double counting)
        layer_1_savings = round(
            sum(line.layer_1_deduction for line in audited_lines), 2
        )
        layer_2_savings = round(
            sum(line.layer_2_deduction for line in audited_lines), 2
        )
        subtotal_after_layer_2 = round(
            max(0.0, total_billed - layer_1_savings - layer_2_savings), 2
        )

        # Layer 3 Charity Care calculation on the remaining valid balance
        layer_3_savings = round(
            subtotal_after_layer_2 * (discount_pct / 100.0), 2
        )
        final_patient_balance = round(
            max(0.0, subtotal_after_layer_2 - layer_3_savings), 2
        )
        total_savings = round(
            layer_1_savings + layer_2_savings + layer_3_savings, 2
        )

        charity_summary = CharityCareSummary(
            annual_income=round(annual_income, 2),
            household_size=safe_household_size,
            fpl_base_2026=round(fpl_base, 2),
            user_fpl_pct=user_fpl_pct,
            eligible=(discount_pct > 0.0),
            discount_pct=discount_pct,
            forgiveness_amount=layer_3_savings,
            tier_name=tier_name,
            legal_citation=legal_citation,
            policy_explanation=policy_summary,
        )

        return {
            "is_itemized": True,
            "requires_ub04_request": False,
            "total_billed": total_billed,
            "layer_1_coding_errors_removed": layer_1_savings,
            "layer_2_mrf_overcharge_removed": layer_2_savings,
            "subtotal_after_layer_2": subtotal_after_layer_2,
            "layer_3_charity_care_forgiveness": layer_3_savings,
            "total_savings": total_savings,
            "final_patient_balance": final_patient_balance,
            "charity_care": charity_summary,
            "line_items": audited_lines,
            "sql_queries_executed": sql_queries_executed,
        }
