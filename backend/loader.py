"""
loader.py - Hospital Insurance JSON Database Loader

Called at the start of main.py:
1. Scans the database/ directory in backend/ where each subdirectory is named after a specific hospital
   (e.g. backend/database/mercy_general_hospital/, backend/database/st_jude_specialty_hospital/)
2. Inside each hospital folder, loads every JSON file named after the insurance company
   (e.g. blue_cross_blue_shield.json, aetna.json, unitedhealthcare.json)
3. Ingests all rate records into DuckDB via query.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
from typing import List, Dict, Any
import query


def _clean_folder_name(name: str) -> str:
    """Converts a snake_case folder name like 'mercy_general_hospital' to 'Mercy General Hospital'."""
    return " ".join(word.capitalize() for word in name.replace("_", " ").split())


def load_hospital_database(database_dir: str = None) -> int:
    """
    Scans the database/ directory for hospital folders and their insurance company JSONs.
    Returns total number of rate records successfully loaded.
    """
    if database_dir is None:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        database_dir = os.path.join(base_dir, "database")

    if not os.path.exists(database_dir):
        # Fallback check for root database/ if called externally
        alt_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "database")
        if os.path.exists(alt_dir):
            database_dir = alt_dir
        else:
            print(f"[loader.py] Warning: database folder not found at {database_dir}")
            return 0

    total_loaded = 0

    for entry in os.listdir(database_dir):
        hospital_path = os.path.join(database_dir, entry)
        if os.path.isdir(hospital_path):
            hospital_folder_name = entry
            inferred_hospital_name = _clean_folder_name(hospital_folder_name)

            json_files = [f for f in os.listdir(hospital_path) if f.endswith(".json")]

            for json_file in json_files:
                file_path = os.path.join(hospital_path, json_file)
                insurance_slug = json_file[:-5]
                inferred_insurance_name = _clean_folder_name(insurance_slug)

                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)

                    records = data if isinstance(data, list) else data.get("rates", [data])
                    normalized_records = []

                    for r in records:
                        rec = dict(r)
                        if not rec.get("hospital"):
                            rec["hospital"] = inferred_hospital_name
                        if not rec.get("insurance_company"):
                            rec["insurance_company"] = inferred_insurance_name
                        normalized_records.append(rec)

                    inserted = query.insert_hospital_rates(normalized_records)
                    total_loaded += inserted
                    print(f"[loader.py] Loaded {inserted} rates from {hospital_folder_name}/{json_file}")
                except Exception as e:
                    print(f"[loader.py] Error reading {file_path}: {e}")

    print(f"[loader.py] Hospital transparency database ready with {total_loaded} total rates.")
    return total_loaded


if __name__ == "__main__":
    count = load_hospital_database()
    print(f"Loaded {count} rates into DuckDB.")
