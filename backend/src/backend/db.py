import duckdb
from backend.config import settings

SUPPORTED_HOSPITALS = [
    "El Camino Health",
    "Stanford Health Care",
    "Santa Clara Valley Medical Center",
    "Other US Hospital",
]

LOCAL_MRF_HOSPITALS = [
    "El Camino Health",
    "Stanford Health Care",
    "Santa Clara Valley Medical Center",
]

SUPPORTED_PAYERS = [
    "Anthem Blue Cross",
    "Aetna",
    "Cigna",
    "UnitedHealthcare",
]

SUPPORTED_LANGUAGES = [
    "English",
    "Russian",
    "Spanish",
    "Vietnamese",
]

# Base CPT catalog with Gross, Payer-specific MRF rates, and Medicare rates
CPT_CATALOG = [
    {
        "cpt_code": "99285",
        "description": "Emergency Dept Visit Level 5",
        "gross_charge": 3800.0,
        "payers": {
            "Anthem Blue Cross": 1150.0,
            "Aetna": 1080.0,
            "Cigna": 1220.0,
            "UnitedHealthcare": 1180.0,
        },
        "medicare_rate": 420.0,
    },
    {
        "cpt_code": "99283",
        "description": "Emergency Dept Visit Level 3",
        "gross_charge": 1650.0,
        "payers": {
            "Anthem Blue Cross": 520.0,
            "Aetna": 490.0,
            "Cigna": 540.0,
            "UnitedHealthcare": 530.0,
        },
        "medicare_rate": 195.0,
    },
    {
        "cpt_code": "70551",
        "description": "MRI Brain w/o Contrast",
        "gross_charge": 4500.0,
        "payers": {
            "Anthem Blue Cross": 1200.0,
            "Aetna": 1100.0,
            "Cigna": 1300.0,
            "UnitedHealthcare": 1250.0,
        },
        "medicare_rate": 290.0,
    },
    {
        "cpt_code": "71045",
        "description": "Chest X-Ray Single View",
        "gross_charge": 680.0,
        "payers": {
            "Anthem Blue Cross": 140.0,
            "Aetna": 125.0,
            "Cigna": 150.0,
            "UnitedHealthcare": 145.0,
        },
        "medicare_rate": 45.0,
    },
    {
        "cpt_code": "12001",
        "description": "Simple Repair of Superficial Wound",
        "gross_charge": 1100.0,
        "payers": {
            "Anthem Blue Cross": 310.0,
            "Aetna": 290.0,
            "Cigna": 330.0,
            "UnitedHealthcare": 320.0,
        },
        "medicare_rate": 115.0,
    },
    {
        "cpt_code": "99070",
        "description": "Surgical Tray / Special Supplies",
        "gross_charge": 450.0,
        "payers": {
            "Anthem Blue Cross": 120.0,
            "Aetna": 110.0,
            "Cigna": 130.0,
            "UnitedHealthcare": 125.0,
        },
        "medicare_rate": 0.0,
    },
    {
        "cpt_code": "36415",
        "description": "Routine Venipuncture / Blood Draw",
        "gross_charge": 185.0,
        "payers": {
            "Anthem Blue Cross": 25.0,
            "Aetna": 22.0,
            "Cigna": 28.0,
            "UnitedHealthcare": 26.0,
        },
        "medicare_rate": 12.0,
    },
    {
        "cpt_code": "80053",
        "description": "Comprehensive Metabolic Panel",
        "gross_charge": 420.0,
        "payers": {
            "Anthem Blue Cross": 48.0,
            "Aetna": 42.0,
            "Cigna": 55.0,
            "UnitedHealthcare": 50.0,
        },
        "medicare_rate": 18.0,
    },
    {
        "cpt_code": "80048",
        "description": "Basic Metabolic Panel",
        "gross_charge": 340.0,
        "payers": {
            "Anthem Blue Cross": 38.0,
            "Aetna": 34.0,
            "Cigna": 42.0,
            "UnitedHealthcare": 40.0,
        },
        "medicare_rate": 14.0,
    },
    {
        "cpt_code": "85025",
        "description": "Complete Blood Count (CBC) w/ Auto Diff",
        "gross_charge": 290.0,
        "payers": {
            "Anthem Blue Cross": 32.0,
            "Aetna": 29.0,
            "Cigna": 35.0,
            "UnitedHealthcare": 33.0,
        },
        "medicare_rate": 11.0,
    },
    {
        "cpt_code": "85027",
        "description": "Complete Blood Count (CBC) Automated",
        "gross_charge": 240.0,
        "payers": {
            "Anthem Blue Cross": 26.0,
            "Aetna": 24.0,
            "Cigna": 28.0,
            "UnitedHealthcare": 27.0,
        },
        "medicare_rate": 9.0,
    },
]

NCCI_SEED_EDITS = [
    (
        "12001",
        "99070",
        "Surgical tray and standard supplies (99070) are integral to wound repair (12001) and cannot be billed separately.",
        "CMS NCCI Policy Manual, Ch. 1, Sec. C — Supplies & Materials",
    ),
    (
        "99285",
        "36415",
        "Routine venipuncture (36415) bundled into Emergency Department facility/evaluation service when performed during same encounter.",
        "CMS NCCI PTP Edit 99285/36415 (Modifier Indicator 0)",
    ),
    (
        "85025",
        "85027",
        "Mutually exclusive laboratory codes: Automated CBC with differential (85025) already includes standard automated CBC (85027).",
        "CMS NCCI Pathology/Laboratory PTP Edit 85025/85027",
    ),
    (
        "80053",
        "80048",
        "Overlapping organ/disease panel: Comprehensive Metabolic Panel (80053) encompasses Basic Metabolic Panel (80048).",
        "CMS NCCI Laboratory Panel Edit 80053/80048",
    ),
]

CHARITY_CARE_SEED_RULES = [
    (
        "Tier 1 — Full Charity Care Forgiveness (<= 200% FPL)",
        0.0,
        200.0,
        100.0,
        "California Health & Safety Code § 127405 (AB 1020) & IRS § 501(r)(4)",
        "Nonprofit hospitals must provide 100% full forgiveness of out-of-pocket balances for patients with household income at or below 200% of the Federal Poverty Level.",
    ),
    (
        "Tier 2 — Extended Financial Assistance Discount (200% - 400% FPL)",
        200.0001,
        400.0,
        65.0,
        "California Health & Safety Code § 127405 (AB 1020) & IRS § 501(r)(5) AGB Limitation",
        "Nonprofit hospitals must cap and discount out-of-pocket balances (even after insurance deductibles/copays) by 65% for patients between 200% and 400% of the Federal Poverty Level.",
    ),
    (
        "Tier 3 — Standard Financial Policy (> 400% FPL)",
        400.0001,
        999999.0,
        0.0,
        "IRS § 501(r) Standard Financial Assistance Threshold",
        "Household income exceeds the 400% FPL statutory threshold for mandatory AB 1020 discount; Layer 1 & Layer 2 coding and MRF rate protections still apply in full.",
    ),
]


def get_connection() -> duckdb.DuckDBPyConnection:
    """Return a DuckDB connection to the configured medbill.duckdb file."""
    return duckdb.connect(settings.DB_PATH)


def init_db() -> None:
    """Initialize medbill.duckdb and populate hospital_prices, medicare_benchmark, ncci_edits, and charity_care_rules."""
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hospital_prices (
                hospital_name VARCHAR,
                payer_name VARCHAR,
                cpt_code VARCHAR,
                description VARCHAR,
                gross_charge DOUBLE,
                allowed_payer_rate DOUBLE,
                medicare_rate DOUBLE,
                PRIMARY KEY (hospital_name, payer_name, cpt_code)
            );
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS medicare_benchmark (
                cpt_code VARCHAR PRIMARY KEY,
                description VARCHAR,
                gross_charge DOUBLE,
                medicare_rate DOUBLE,
                fair_allowed_amount DOUBLE
            );
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ncci_edits (
                column_1_cpt VARCHAR,
                column_2_cpt VARCHAR,
                violation_reason VARCHAR,
                cms_citation VARCHAR,
                PRIMARY KEY (column_1_cpt, column_2_cpt)
            );
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS charity_care_rules (
                tier_name VARCHAR PRIMARY KEY,
                min_fpl_pct DOUBLE,
                max_fpl_pct DOUBLE,
                discount_pct DOUBLE,
                legal_citation VARCHAR,
                policy_summary VARCHAR
            );
            """
        )

        # Populate hospital_prices
        price_count = conn.execute("SELECT COUNT(*) FROM hospital_prices").fetchone()[0]
        if price_count == 0:
            hospital_rows = []
            for hospital in LOCAL_MRF_HOSPITALS:
                for item in CPT_CATALOG:
                    for payer_name, allowed_rate in item["payers"].items():
                        hospital_rows.append(
                            (
                                hospital,
                                payer_name,
                                item["cpt_code"],
                                item["description"],
                                item["gross_charge"],
                                allowed_rate,
                                item["medicare_rate"],
                            )
                        )
            conn.executemany(
                """
                INSERT INTO hospital_prices (
                    hospital_name, payer_name, cpt_code, description,
                    gross_charge, allowed_payer_rate, medicare_rate
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                hospital_rows,
            )

        # Populate medicare_benchmark
        bench_count = conn.execute("SELECT COUNT(*) FROM medicare_benchmark").fetchone()[0]
        if bench_count == 0:
            bench_rows = [
                (
                    item["cpt_code"],
                    item["description"],
                    item["gross_charge"],
                    item["medicare_rate"],
                    round(item["medicare_rate"] * 1.8, 2),
                )
                for item in CPT_CATALOG
            ]
            conn.executemany(
                """
                INSERT INTO medicare_benchmark (
                    cpt_code, description, gross_charge, medicare_rate, fair_allowed_amount
                ) VALUES (?, ?, ?, ?, ?)
                """,
                bench_rows,
            )

        # Populate ncci_edits
        ncci_count = conn.execute("SELECT COUNT(*) FROM ncci_edits").fetchone()[0]
        if ncci_count == 0:
            conn.executemany(
                """
                INSERT INTO ncci_edits (
                    column_1_cpt, column_2_cpt, violation_reason, cms_citation
                ) VALUES (?, ?, ?, ?)
                """,
                NCCI_SEED_EDITS,
            )

        # Populate charity_care_rules
        cc_count = conn.execute("SELECT COUNT(*) FROM charity_care_rules").fetchone()[0]
        if cc_count == 0:
            conn.executemany(
                """
                INSERT INTO charity_care_rules (
                    tier_name, min_fpl_pct, max_fpl_pct, discount_pct, legal_citation, policy_summary
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                CHARITY_CARE_SEED_RULES,
            )
