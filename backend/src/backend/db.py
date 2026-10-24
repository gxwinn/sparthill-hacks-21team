from pathlib import Path
from typing import Any
import duckdb
from backend.config import settings

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"

AUTO_DETECT_OPTION = "Auto-Detect from Bill"

LOCAL_MRF_HOSPITALS = [
    "El Camino Health",
    "Stanford Health Care",
    "Santa Clara Valley Medical Center",
]

SUPPORTED_HOSPITALS = [
    AUTO_DETECT_OPTION,
    "El Camino Health",
    "Stanford Health Care",
    "Santa Clara Valley Medical Center",
    "Other US Hospital",
]

LOCAL_MRF_PAYERS = [
    "Anthem Blue Cross",
    "Aetna",
    "Cigna",
    "UnitedHealthcare",
]

OTHER_INSURANCE_OPTION = "Other Insurance / Out-of-Network (Median MRF / Federal Cap)"
UNINSURED_SELF_PAY_OPTION = "Uninsured / Self-Pay (Federal Medicare Benchmark + Charity Care)"

SUPPORTED_PAYERS = [
    AUTO_DETECT_OPTION,
    "Anthem Blue Cross",
    "Aetna",
    "Cigna",
    "UnitedHealthcare",
    OTHER_INSURANCE_OPTION,
    UNINSURED_SELF_PAY_OPTION,
]

SUPPORTED_LANGUAGES = [
    "English",
    "Russian",
    "Spanish",
    "Vietnamese",
]


def _ensure_csv_datasets_exist() -> None:
    """Ensure the structured CSV datasets in `data/` exist before DuckDB ingestion."""
    required_files = [
        DATA_DIR / "cms_medicare_pfs.csv",
        DATA_DIR / "hospital_mrf_rates.csv",
        DATA_DIR / "cms_ncci_edits.csv",
        DATA_DIR / "ub04_revenue_code_rules.csv",
        DATA_DIR / "charity_care_fpl_tiers.csv",
        DATA_DIR / "data_governance_sources.csv",
    ]
    if all(p.exists() for p in required_files):
        return

    import sys

    scripts_parent = str(PROJECT_ROOT)
    if scripts_parent not in sys.path:
        sys.path.insert(0, scripts_parent)
    from scripts.fetch_and_build_data import build_all_reference_csvs

    build_all_reference_csvs(DATA_DIR)


def get_connection() -> duckdb.DuckDBPyConnection:
    """Return a DuckDB connection to the configured medbill.duckdb file."""
    return duckdb.connect(settings.DB_PATH)


def init_db() -> None:
    """
    Initialize medbill.duckdb strictly by loading structured reference CSV datasets
    from `<project_root>/data/*.csv` using DuckDB `read_csv_auto`.
    """
    _ensure_csv_datasets_exist()

    mrf_csv = (DATA_DIR / "hospital_mrf_rates.csv").resolve().as_posix()
    pfs_csv = (DATA_DIR / "cms_medicare_pfs.csv").resolve().as_posix()
    ncci_csv = (DATA_DIR / "cms_ncci_edits.csv").resolve().as_posix()
    ub04_csv = (DATA_DIR / "ub04_revenue_code_rules.csv").resolve().as_posix()
    cc_csv = (DATA_DIR / "charity_care_fpl_tiers.csv").resolve().as_posix()
    gov_csv = (DATA_DIR / "data_governance_sources.csv").resolve().as_posix()

    with get_connection() as conn:
        # 1. Hospital MRF Negotiated Payer Rates (45 CFR § 180.50)
        conn.execute(
            f"""
            CREATE OR REPLACE TABLE hospital_prices AS
            SELECT
                CAST(hospital_name AS VARCHAR) AS hospital_name,
                CAST(payer_name AS VARCHAR) AS payer_name,
                CAST(cpt_code AS VARCHAR) AS cpt_code,
                CAST(description AS VARCHAR) AS description,
                CAST(gross_charge AS DOUBLE) AS gross_charge,
                CAST(allowed_payer_rate AS DOUBLE) AS allowed_payer_rate,
                CAST(medicare_rate AS DOUBLE) AS medicare_rate,
                CAST(mrf_source_citation AS VARCHAR) AS mrf_source_citation
            FROM read_csv_auto('{mrf_csv}', header=true, all_varchar=true, encoding='utf-8');
            """
        )

        # 2. CMS Medicare Physician Fee Schedule (PFS) & Clinical Lab Fee Schedule (CLFS)
        conn.execute(
            f"""
            CREATE OR REPLACE TABLE medicare_benchmark AS
            SELECT
                CAST(cpt_code AS VARCHAR) AS cpt_code,
                CAST(code_type AS VARCHAR) AS code_type,
                CAST(category AS VARCHAR) AS category,
                CAST(description AS VARCHAR) AS description,
                CAST(gross_charge AS DOUBLE) AS gross_charge,
                CAST(medicare_rate AS DOUBLE) AS medicare_rate,
                CAST(fair_allowed_amount AS DOUBLE) AS fair_allowed_amount,
                CAST(cms_status AS VARCHAR) AS cms_status,
                CAST(source_authority AS VARCHAR) AS source_authority
            FROM read_csv_auto('{pfs_csv}', header=true, all_varchar=true, encoding='utf-8');
            """
        )

        # 3. CMS National Correct Coding Initiative (NCCI) PTP Bundling Edits
        conn.execute(
            f"""
            CREATE OR REPLACE TABLE ncci_edits AS
            SELECT
                CAST(column_1_cpt AS VARCHAR) AS column_1_cpt,
                CAST(column_2_cpt AS VARCHAR) AS column_2_cpt,
                CAST(modifier_indicator AS VARCHAR) AS modifier_indicator,
                CAST(effective_date AS VARCHAR) AS effective_date,
                CAST(violation_reason AS VARCHAR) AS violation_reason,
                CAST(cms_citation AS VARCHAR) AS cms_citation
            FROM read_csv_auto('{ncci_csv}', header=true, all_varchar=true, encoding='utf-8');
            """
        )

        # 4. CMS Form UB-04 (CMS-1450) 4-Digit Revenue Code Itemization Rules
        conn.execute(
            f"""
            CREATE OR REPLACE TABLE ub04_revenue_rules AS
            SELECT
                CAST(rev_code AS VARCHAR) AS rev_code,
                CAST(rev_description AS VARCHAR) AS rev_description,
                CAST(LOWER(requires_hcpcs_ndc) = 'true' AS BOOLEAN) AS requires_hcpcs_ndc,
                CAST(medicare_base_allowance AS DOUBLE) AS medicare_base_allowance,
                CAST(violation_title AS VARCHAR) AS violation_title,
                CAST(cms_citation AS VARCHAR) AS cms_citation,
                CAST(violation_reason AS VARCHAR) AS violation_reason
            FROM read_csv_auto('{ub04_csv}', header=true, all_varchar=true, encoding='utf-8');
            """
        )

        # 5. California AB 1020 & IRS § 501(r) Charity Care FPL Tiers
        conn.execute(
            f"""
            CREATE OR REPLACE TABLE charity_care_rules AS
            SELECT
                CAST(tier_name AS VARCHAR) AS tier_name,
                CAST(min_fpl_pct AS DOUBLE) AS min_fpl_pct,
                CAST(max_fpl_pct AS DOUBLE) AS max_fpl_pct,
                CAST(discount_pct AS DOUBLE) AS discount_pct,
                CAST(legal_citation AS VARCHAR) AS legal_citation,
                CAST(policy_summary AS VARCHAR) AS policy_summary
            FROM read_csv_auto('{cc_csv}', header=true, all_varchar=true, encoding='utf-8');
            """
        )

        # 6. Data Provenance & Governance Registry
        conn.execute(
            f"""
            CREATE OR REPLACE TABLE data_governance_sources AS
            SELECT
                CAST(dataset_id AS VARCHAR) AS dataset_id,
                CAST(dataset_name AS VARCHAR) AS dataset_name,
                CAST(csv_file AS VARCHAR) AS csv_file,
                CAST(regulatory_authority AS VARCHAR) AS regulatory_authority,
                CAST(statutory_citation AS VARCHAR) AS statutory_citation,
                CAST(source_url AS VARCHAR) AS source_url,
                CAST(effective_date AS VARCHAR) AS effective_date,
                CAST(verification_notes AS VARCHAR) AS verification_notes
            FROM read_csv_auto('{gov_csv}', header=true, all_varchar=true, encoding='utf-8');
            """
        )


def get_data_governance_sources() -> list[dict[str, Any]]:
    """Return all regulatory dataset provenance rows from DuckDB `data_governance_sources`."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                dataset_id,
                dataset_name,
                csv_file,
                regulatory_authority,
                statutory_citation,
                source_url,
                effective_date,
                verification_notes
            FROM data_governance_sources
            ORDER BY dataset_id
            """
        ).fetchall()
    return [
        {
            "dataset_id": r[0],
            "dataset_name": r[1],
            "csv_file": r[2],
            "regulatory_authority": r[3],
            "statutory_citation": r[4],
            "source_url": r[5],
            "effective_date": r[6],
            "verification_notes": r[7],
        }
        for r in rows
    ]
