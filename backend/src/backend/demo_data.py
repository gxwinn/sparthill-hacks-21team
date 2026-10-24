from typing import Any

DEMO_BILLS: dict[str, dict[str, Any]] = {
    "demo_1_er_trauma": {
        "demo_id": "demo_1_er_trauma",
        "title": "Demo 1: ER Trauma & Wound Repair Bill ($10,955 billed)",
        "subtitle": "Triggers NCCI unbundling (99285+36415, 12001+99070) + MRF overcharge + Charity Care",
        "patient_name": "Elena Rostova",
        "patient_address": "1140 W El Camino Real, Mountain View, CA 94040",
        "account_number": "ECH-2026-88412",
        "dob": "1984-07-19",
        "hospital_name": "El Camino Health",
        "default_payer": "Anthem Blue Cross",
        "default_income": 48000.0,
        "default_household_size": 3,
        "is_itemized": True,
        "line_items": [
            {
                "cpt_code": "99285",
                "description": "Emergency Dept Visit Level 5",
                "quantity": 1,
                "billed_amount": 3800.00,
            },
            {
                "cpt_code": "70551",
                "description": "MRI Brain w/o Contrast",
                "quantity": 1,
                "billed_amount": 4500.00,
            },
            {
                "cpt_code": "71045",
                "description": "Chest X-Ray Single View",
                "quantity": 1,
                "billed_amount": 680.00,
            },
            {
                "cpt_code": "12001",
                "description": "Simple Repair of Superficial Wound",
                "quantity": 1,
                "billed_amount": 1100.00,
            },
            {
                "cpt_code": "99070",
                "description": "Surgical Tray / Special Supplies",
                "quantity": 1,
                "billed_amount": 450.00,
            },
            {
                "cpt_code": "36415",
                "description": "Routine Venipuncture / Blood Draw",
                "quantity": 1,
                "billed_amount": 185.00,
            },
            {
                "cpt_code": "85027",
                "description": "Complete Blood Count (CBC) Automated",
                "quantity": 1,
                "billed_amount": 240.00,
            },
        ],
    },
    "demo_2_duplicate_labs": {
        "demo_id": "demo_2_duplicate_labs",
        "title": "Demo 2: Duplicate Lab & Blood Panel Bill ($3,545 billed)",
        "subtitle": "Triggers Duplicate CPT (80053 x2) + NCCI overlapping lab edits (85025+85027, 80053+80048) + MRF overcharge",
        "patient_name": "Marcus Vance",
        "patient_address": "500 Pasteur Dr, Palo Alto, CA 94304",
        "account_number": "SHC-2026-44109",
        "dob": "1979-11-03",
        "hospital_name": "Stanford Health Care",
        "default_payer": "Aetna",
        "default_income": 72000.0,
        "default_household_size": 3,
        "is_itemized": True,
        "line_items": [
            {
                "cpt_code": "99283",
                "description": "Emergency Dept Visit Level 3",
                "quantity": 1,
                "billed_amount": 1650.00,
            },
            {
                "cpt_code": "80053",
                "description": "Comprehensive Metabolic Panel",
                "quantity": 1,
                "billed_amount": 420.00,
            },
            {
                "cpt_code": "80053",
                "description": "Comprehensive Metabolic Panel (Repeat Billing)",
                "quantity": 1,
                "billed_amount": 420.00,
            },
            {
                "cpt_code": "80048",
                "description": "Basic Metabolic Panel",
                "quantity": 1,
                "billed_amount": 340.00,
            },
            {
                "cpt_code": "85025",
                "description": "Complete Blood Count (CBC) w/ Auto Diff",
                "quantity": 1,
                "billed_amount": 290.00,
            },
            {
                "cpt_code": "85027",
                "description": "Complete Blood Count (CBC) Automated",
                "quantity": 1,
                "billed_amount": 240.00,
            },
            {
                "cpt_code": "36415",
                "description": "Routine Venipuncture / Blood Draw",
                "quantity": 1,
                "billed_amount": 185.00,
            },
        ],
    },
    "demo_3_summary_bill": {
        "demo_id": "demo_3_summary_bill",
        "title": "Demo 3: Non-Itemized Summary Bill ($8,450 billed)",
        "subtitle": "Missing 5-digit CPT/HCPCS codes -> skips price/NCCI audit & generates HIPAA Itemized Bill (UB-04) Request Letter",
        "patient_name": "Minh Nguyen",
        "patient_address": "751 S Bascom Ave, San Jose, CA 95128",
        "account_number": "SCVMC-2026-10294",
        "dob": "1991-02-25",
        "hospital_name": "Santa Clara Valley Medical Center",
        "default_payer": "Cigna",
        "default_income": 42000.0,
        "default_household_size": 2,
        "is_itemized": False,
        "line_items": [
            {
                "cpt_code": "",
                "description": "Emergency Room Services — Consolidated Summary Charge",
                "quantity": 1,
                "billed_amount": 3800.00,
            },
            {
                "cpt_code": "",
                "description": "Diagnostic Imaging & Radiology — General Dept Summary",
                "quantity": 1,
                "billed_amount": 2600.00,
            },
            {
                "cpt_code": "",
                "description": "Medical / Surgical Supplies & Pharmacy — Consolidated",
                "quantity": 1,
                "billed_amount": 1250.00,
            },
            {
                "cpt_code": "",
                "description": "Clinical Laboratory Services — General Summary",
                "quantity": 1,
                "billed_amount": 800.00,
            },
        ],
    },
}

DEMO_ALIASES: dict[str, str] = {
    "1": "demo_1_er_trauma",
    "demo_1": "demo_1_er_trauma",
    "demo_1_er_trauma": "demo_1_er_trauma",
    "er": "demo_1_er_trauma",
    "er_visit": "demo_1_er_trauma",
    "2": "demo_2_duplicate_labs",
    "demo_2": "demo_2_duplicate_labs",
    "demo_2_duplicate_labs": "demo_2_duplicate_labs",
    "labs": "demo_2_duplicate_labs",
    "surgery": "demo_2_duplicate_labs",
    "3": "demo_3_summary_bill",
    "demo_3": "demo_3_summary_bill",
    "demo_3_summary_bill": "demo_3_summary_bill",
    "summary": "demo_3_summary_bill",
}


def get_demo_bill(demo_id: str) -> dict[str, Any]:
    normalized = DEMO_ALIASES.get(demo_id.strip().lower(), "demo_1_er_trauma")
    return DEMO_BILLS[normalized]


def list_demo_Metadata() -> list[dict[str, Any]]:
    result = []
    for key, demo in DEMO_BILLS.items():
        total_billed = sum(item["billed_amount"] for item in demo["line_items"])
        result.append(
            {
                "demo_id": key,
                "title": demo["title"],
                "subtitle": demo["subtitle"],
                "hospital_name": demo["hospital_name"],
                "default_payer": demo["default_payer"],
                "default_income": demo["default_income"],
                "default_household_size": demo["default_household_size"],
                "is_itemized": demo["is_itemized"],
                "total_billed": round(total_billed, 2),
                "line_count": len(demo["line_items"]),
            }
        )
    return result
