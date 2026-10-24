# BillAudit AI - Medical Bill Error & Savings Scanner

An AI-powered medical bill auditing system that detects billing discrepancies, unbundled charges, and compares stated prices against hospital-negotiated insurance rates using Google Gemini, DuckDB, and Pydantic.

---

## Key Features

1. **Database Organization by Hospital Folders**:
   - `database/<hospital_name>/<insurance_company>.json`
   - e.g. `database/mercy_general_hospital/blue_cross_blue_shield.json`, `database/st_jude_specialty_hospital/aetna.json`.
   - `loader.py` dynamically scans all hospital subdirectories on startup and populates DuckDB.

2. **2-Stage Database Query Strategy**:
   - **Stage 1 (Code-first)**: First queries DuckDB with the procedure `code`. If matched by code, no user confirmation is required.
   - **Stage 2 (Name fallback)**: If the code is not found or null, queries DuckDB by procedure `name`. When matched by name, asks the user to confirm:
     *`"Is '[matched_name]' (Code: [code]) what you meant by '[stated_name]'?"`*

3. **Manual Bill Option (Forgo Image Upload)**:
   - Users can forgo uploading an image and submit bill details directly via `POST /manual-bill`.

4. **Streamlined Final Bill Schema**:
   - `calculatedPrice` and `userinfo` are removed.
   - Each procedure line contains: `{ "code": ..., "initialPrice": ..., "negotiatedPrice": ... }`.
   - Sums all negotiated rates into `negotiatedFinalTotalBill`.

---

## Directory Structure

```
├── main.py                           # FastAPI orchestration endpoint
├── Gemini.py                         # Vision extraction using Gemini API & Pydantic
├── Calculator.py                     # Bill calculation calling query.py
├── query.py                          # 2-stage DuckDB search (code first, then name)
├── loader.py                         # Loads database/<hospital>/<insurance>.json
├── database/
│   ├── mercy_general_hospital/
│   │   ├── blue_cross_blue_shield.json
│   │   └── aetna.json
│   ├── st_jude_specialty_hospital/
│   │   └── aetna.json
│   └── metro_university_heart_center/
│       └── unitedhealthcare.json
├── schema/
│   ├── __init__.py
│   └── models.py                     # UserJson & FinalBillJson
├── requirements.txt                  # Python dependencies
└── src/
    └── App.tsx                       # Interactive UI & schema dashboard
```

---

## Schemas

### `userJson` (Input)
```json
{
  "hospital": "Mercy General Hospital",
  "insurance company": "Blue Cross Blue Shield",
  "patientProcedures": [
    {
      "name": "Emergency Room Visit Level 4 (CPT 99284)",
      "code": "99284",
      "statedPrice": 1850.00
    }
  ]
}
```

### `finalbilljson` (Output)
```json
{
  "hospital": "Mercy General Hospital",
  "insurance company": "Blue Cross Blue Shield",
  "initialTotalBill": 1850.00,
  "negotiatedFinalTotalBill": 620.00,
  "finalTotalBill": 620.00,
  "Emergency Room Visit Level 4 (CPT 99284)": {
    "code": "99284",
    "initialPrice": 1850.00,
    "negotiatedPrice": 620.00
  }
}
```

---

## API Endpoints

- `POST /scan-bill`: Multipart photo upload. Unclear fields set to `null`; prompts for re-upload or manual input.
- `POST /manual-bill`: Forgoes photo upload; accepts structured `UserJson` directly.
- `POST /confirm-procedures`: Confirms name-matched procedures and finalizes calculation.
