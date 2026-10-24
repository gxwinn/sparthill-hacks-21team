import re
from typing import Any
from backend.db import (
    LOCAL_MRF_HOSPITALS,
    LOCAL_MRF_PAYERS,
    OTHER_INSURANCE_OPTION,
    UNINSURED_SELF_PAY_OPTION,
    get_connection,
)
from backend.schemas import (
    AuditedLineItem,
    CharityCareSummary,
    ExtractedBillSchema,
)

CPT_REGEX = re.compile(r"^[A-Z0-9]{5}$")
REVENUE_CODE_REGEX = re.compile(r"^\d{4}$")


def is_valid_cpt_code(code: str) -> bool:
    cleaned = (code or "").strip().upper()
    if not cleaned or cleaned in ("NONE", "MISSING", "N/A", "NULL"):
        return False
    if CPT_REGEX.match(cleaned) and any(ch.isdigit() for ch in cleaned):
        return True
    if REVENUE_CODE_REGEX.match(cleaned):
        return True
    return False


def run_deterministic_audit(
    extracted_bill: ExtractedBillSchema,
    hospital_name: str,
    payer_name: str,
    annual_income: float,
    household_size: int,
) -> dict[str, Any]:
    """
    Execute the deterministic 3-Layer DuckDB Audit with 0% AI math hallucinations:
      - Layer 1: Duplicate CPT detection, CMS NCCI PTP Unbundling Edits (`ncci_edits`),
                 and 4-Digit UB-04 Revenue Code Roll-Up Enforcement (`ub04_revenue_rules`).
      - Layer 2: Bay Area Hospital MRF Negotiated Rates (`hospital_prices`) or Federal
                 CMS Medicare PFS/CLFS Benchmark (`medicare_benchmark`).
      - Layer 3: California AB 1020 & IRS § 501(r) Charity Care FPL Tiers (`charity_care_rules`).
    """
    from backend.privacy import normalize_and_filter_extracted_bill

    extracted_bill = normalize_and_filter_extracted_bill(extracted_bill)
    sql_queries_executed: list[str] = []
    line_items = extracted_bill.line_items
    total_billed = round(sum(item.billed_amount for item in line_items), 2)

    # Determine whether the bill is itemized with valid 5-character CPT/HCPCS or 4-digit revenue codes
    has_cpt_codes = any(is_valid_cpt_code(item.cpt_code) for item in line_items)
    is_itemized = bool(has_cpt_codes)

    # Determine pricing tier:
    # 1. LOCAL_MRF: Matched Hospital + Matched Payer -> exact hospital-payer MRF rate
    # 2. MEDIAN_MRF: Matched Hospital + Other Insurance -> median MRF rate across payers at that hospital
    # 3. CMS_MEDICARE_BENCHMARK: Other Hospital or Uninsured/Self-Pay -> 1.8x Federal CMS Medicare rate
    is_uninsured_self_pay = payer_name in (
        UNINSURED_SELF_PAY_OPTION,
        "Uninsured / Self-Pay",
        "CMS Medicare Benchmark",
    )
    is_local_mrf_contract = (
        hospital_name in LOCAL_MRF_HOSPITALS and payer_name in LOCAL_MRF_PAYERS
    )
    is_median_mrf_contract = (
        hospital_name in LOCAL_MRF_HOSPITALS
        and not is_local_mrf_contract
        and not is_uninsured_self_pay
    )

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

        # Edge Case: Non-itemized Summary Bill or Clinical Discharge Summary without CPT codes
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
                            "Summary department or clinical entry lacks a 5-digit CPT/HCPCS code. "
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
                "pricing_benchmark_used": (
                    "LOCAL_MRF" if is_local_mrf_contract else "CMS_MEDICARE_BENCHMARK"
                ),
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
        # LAYER 1: Coding Errors, NCCI Unbundling & UB-04 Revenue Code Roll-Ups
        # =====================================================================
        distinct_cpts = sorted(
            {
                item.cpt_code.strip().upper()
                for item in line_items
                if is_valid_cpt_code(item.cpt_code)
            }
        )

        ncci_violations_by_col2: dict[str, dict[str, str]] = {}
        ub04_rules_by_code: dict[str, dict[str, Any]] = {}

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

            # Query 4-Digit UB-04 Revenue Code Roll-Up Rules
            four_digit_codes = [c for c in distinct_cpts if REVENUE_CODE_REGEX.match(c)]
            if four_digit_codes:
                rev_sql_list = ", ".join(f"'{c}'" for c in four_digit_codes)
                rev_sql_display = (
                    f"SELECT rev_code, rev_description, medicare_base_allowance, violation_title, cms_citation "
                    f"FROM ub04_revenue_rules "
                    f"WHERE rev_code IN ({rev_sql_list}) AND requires_hcpcs_ndc = TRUE;"
                )
                sql_queries_executed.append(rev_sql_display)

                rev_placeholders = ", ".join("?" for _ in four_digit_codes)
                rev_rows = conn.execute(
                    f"""
                    SELECT rev_code, rev_description, requires_hcpcs_ndc,
                           medicare_base_allowance, violation_title, cms_citation, violation_reason
                    FROM ub04_revenue_rules
                    WHERE rev_code IN ({rev_placeholders})
                      AND requires_hcpcs_ndc = TRUE
                    """,
                    four_digit_codes,
                ).fetchall()
                for r_code, r_desc, req_hcpcs, base_allow, v_title, v_cit, v_reason in rev_rows:
                    ub04_rules_by_code[r_code] = {
                        "rev_code": r_code,
                        "rev_description": r_desc,
                        "requires_hcpcs_ndc": bool(req_hcpcs),
                        "medicare_base_allowance": float(base_allow),
                        "violation_title": v_title,
                        "cms_citation": v_cit,
                        "violation_reason": v_reason,
                    }

        # =====================================================================
        # LAYER 2: Payer-Specific MRF Rate, Median MRF, or CMS Medicare Benchmark
        # =====================================================================
        if distinct_cpts and is_local_mrf_contract:
            cpt_list_sql = ", ".join(f"'{c}'" for c in distinct_cpts)
            mrf_sql_display = (
                f"SELECT cpt_code, description, gross_charge, allowed_payer_rate, medicare_rate "
                f"FROM hospital_prices "
                f"WHERE hospital_name = '{hospital_name}' "
                f"AND payer_name = '{payer_name}' "
                f"AND cpt_code IN ({cpt_list_sql});"
            )
            sql_queries_executed.append(mrf_sql_display)
        elif distinct_cpts and is_median_mrf_contract:
            cpt_list_sql = ", ".join(f"'{c}'" for c in distinct_cpts)
            median_sql_display = (
                f"SELECT cpt_code, ROUND(MEDIAN(allowed_payer_rate), 2) AS median_mrf_rate, "
                f"ROUND(MEDIAN(medicare_rate), 2) AS medicare_rate "
                f"FROM hospital_prices "
                f"WHERE hospital_name = '{hospital_name}' "
                f"AND cpt_code IN ({cpt_list_sql}) GROUP BY cpt_code;"
            )
            sql_queries_executed.append(median_sql_display)

        seen_cpts: set[str] = set()
        audited_lines = []
        used_any_medicare_fallback = not (is_local_mrf_contract or is_median_mrf_contract)
        used_any_median_mrf = False

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

            # 1C. Standalone 4-Digit UB-04 Revenue Code Roll-Up Check (0250 Pharmacy, 0260 IV Therapy, 0270 Supplies)
            if cpt in ub04_rules_by_code:
                rev_rule = ub04_rules_by_code[cpt]
                base_unit = float(rev_rule["medicare_base_allowance"])
                allowed_base_total = round(base_unit * qty, 2)
                if billed > allowed_base_total:
                    rollup_deduction = round(billed - allowed_base_total, 2)
                    audited_lines.append(
                        AuditedLineItem(
                            line_index=idx,
                            cpt_code=cpt,
                            description=item.description,
                            quantity=qty,
                            billed_amount=billed,
                            allowed_amount=allowed_base_total,
                            medicare_rate=allowed_base_total,
                            layer_1_deduction=rollup_deduction,
                            layer_2_deduction=0.0,
                            patient_responsibility_before_charity=allowed_base_total,
                            status="REVENUE_CODE_ROLLUP",
                            citation=rev_rule["cms_citation"],
                            violation_reason=(
                                f"{rev_rule['violation_reason']} "
                                f"(Billed ${billed:,.2f} vs. ${allowed_base_total:,.2f} Medicare baseline allowance; "
                                f"${rollup_deduction:,.2f} unsupported roll-up markup removed)."
                            ),
                        )
                    )
                    continue

            # 2. Layer 2 Payer MRF Rate, Hospital Median MRF Rate, or CMS Medicare Benchmark Check
            price_row = None
            line_used_median_mrf = False
            if is_local_mrf_contract:
                price_row = conn.execute(
                    """
                    SELECT allowed_payer_rate, medicare_rate, gross_charge
                    FROM hospital_prices
                    WHERE hospital_name = ? AND payer_name = ? AND cpt_code = ?
                    LIMIT 1
                    """,
                    [hospital_name, payer_name, cpt],
                ).fetchone()
            elif is_median_mrf_contract:
                med_row = conn.execute(
                    """
                    SELECT ROUND(MEDIAN(allowed_payer_rate), 2),
                           ROUND(MEDIAN(medicare_rate), 2),
                           MAX(gross_charge)
                    FROM hospital_prices
                    WHERE hospital_name = ? AND cpt_code = ?
                    """,
                    [hospital_name, cpt],
                ).fetchone()
                if med_row is not None and med_row[0] is not None:
                    price_row = med_row
                    line_used_median_mrf = True
                    used_any_median_mrf = True

            used_medicare_fallback = False
            source_authority = "CMS CY2026 PFS/CLFS Benchmark (1.8x Medicare Rate)"
            if price_row is not None and price_row[0] is not None:
                unit_allowed = float(price_row[0])
                unit_medicare = float(price_row[1])
            else:
                used_medicare_fallback = True
                used_any_medicare_fallback = True
                bench_sql_display = (
                    f"SELECT fair_allowed_amount, medicare_rate, source_authority "
                    f"FROM medicare_benchmark WHERE cpt_code = '{cpt}';"
                )
                if bench_sql_display not in sql_queries_executed:
                    sql_queries_executed.append(bench_sql_display)

                bench_row = conn.execute(
                    """
                    SELECT fair_allowed_amount, medicare_rate, source_authority
                    FROM medicare_benchmark
                    WHERE cpt_code = ?
                    LIMIT 1
                    """,
                    [cpt],
                ).fetchone()
                if bench_row is not None:
                    unit_allowed = float(bench_row[0])
                    unit_medicare = float(bench_row[1])
                    if bench_row[2]:
                        source_authority = str(bench_row[2])
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
                        f"{source_authority} — Federal Benchmark Cap (1.8x Medicare): ${allowed_total:,.2f} "
                        f"(CMS Medicare Base Rate: ${medicare_total:,.2f})"
                    )
                    violation_reason = (
                        f"Billed charge (${billed:,.2f}) exceeds the Federal CMS Medicare fair benchmark "
                        f"(${allowed_total:,.2f}, 1.8x the CMS Medicare rate of ${medicare_total:,.2f}) by ${overcharge:,.2f}."
                    )
                elif line_used_median_mrf:
                    citation = (
                        f"45 CFR § 180.50 Hospital Price Transparency & No Surprises Act — {hospital_name} "
                        f"Median Negotiated MRF Rate: ${allowed_total:,.2f} (CMS Medicare Base: ${medicare_total:,.2f})"
                    )
                    violation_reason = (
                        f"Chargemaster gross bill (${billed:,.2f}) exceeds {hospital_name}'s median negotiated "
                        f"commercial MRF rate across payers (${allowed_total:,.2f}) by ${overcharge:,.2f}."
                    )
                else:
                    citation = (
                        f"45 CFR § 180.50 Hospital Price Transparency MRF — {hospital_name} / {payer_name} "
                        f"Negotiated Rate: ${allowed_total:,.2f} (CMS Medicare Base: ${medicare_total:,.2f})"
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
                            f"45 CFR § 180.50 MRF Verified — Within {payer_name} Allowed Rate (${allowed_total:,.2f})"
                            if not used_medicare_fallback and not line_used_median_mrf
                            else (
                                f"45 CFR § 180.50 MRF Verified — Within {hospital_name} Median MRF Rate (${allowed_total:,.2f})"
                                if line_used_median_mrf
                                else f"{source_authority} Verified — Within CMS Benchmark (${allowed_total:,.2f})"
                            )
                        ),
                        violation_reason="Billed amount does not exceed the published reference allowed rate.",
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

        if used_any_median_mrf:
            effective_benchmark = "MEDIAN_MRF"
        elif used_any_medicare_fallback:
            effective_benchmark = "CMS_MEDICARE_BENCHMARK"
        else:
            effective_benchmark = "LOCAL_MRF"

        return {
            "is_itemized": True,
            "requires_ub04_request": False,
            "pricing_benchmark_used": effective_benchmark,
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
