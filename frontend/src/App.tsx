import React, { useState } from 'react';
import {
  FileText,
  Upload,
  CheckCircle2,
  AlertTriangle,
  ArrowRight,
  Database,
  Cpu,
  Calculator as CalcIcon,
  Code2,
  DollarSign,
  TrendingDown,
  Layers,
  Copy,
  Check,
  ChevronRight,
  Sparkles,
  Info,
  ShieldCheck,
  Search,
  RefreshCw,
  Edit3,
  FolderTree,
  Plus,
  Trash2,
  HelpCircle,
  Camera,
  CheckCheck,
  FolderCode,
  FileCode2,
  Server,
  Monitor
} from 'lucide-react';

interface ProcedureItem {
  name: string | null;
  code: string | null;
  statedPrice: number | null;
  negotiatedPrice?: number;
  category: string;
}

interface SampleBill {
  id: string;
  title: string;
  hospital: string | null;
  insurance: string | null;
  isUnclear: boolean;
  unclearReason?: string;
  description: string;
  procedures: ProcedureItem[];
}

const SAMPLE_BILLS: SampleBill[] = [
  {
    id: 'sample-1',
    title: 'Emergency Room & Imaging (Code Matched)',
    hospital: 'Mercy General Hospital',
    insurance: 'Blue Cross Blue Shield',
    isUnclear: false,
    description: 'All procedures have verified CPT codes and match hospital database directly.',
    procedures: [
      { name: 'Emergency Room Visit Level 4 (CPT 99284)', code: '99284', statedPrice: 1850.0, negotiatedPrice: 620.0, category: 'Evaluation' },
      { name: 'CT Abdomen & Pelvis with Contrast (CPT 74177)', code: '74177', statedPrice: 3200.0, negotiatedPrice: 850.0, category: 'Radiology' },
      { name: 'Comprehensive Metabolic Panel (CPT 80053)', code: '80053', statedPrice: 340.0, negotiatedPrice: 68.0, category: 'Lab' },
      { name: 'IV Hydration Infusion First Hour (CPT 96360)', code: '96360', statedPrice: 520.0, negotiatedPrice: 110.0, category: 'Infusion' },
    ],
  },
  {
    id: 'sample-name-match',
    title: 'Orthopedic Arthroscopy (Name Matched -> Confirm)',
    hospital: 'St. Jude Specialty Hospital',
    insurance: 'Aetna Health HMO',
    isUnclear: false,
    description: 'Code was not found, so DuckDB queried by name. Prompts user to confirm match.',
    procedures: [
      { name: 'Knee Arthroscopy Meniscectomy', code: null, statedPrice: 6800.0, negotiatedPrice: 2150.0, category: 'Surgical' },
      { name: 'Anesthesia Services Moderate (CPT 01400)', code: '01400', statedPrice: 2100.0, negotiatedPrice: 540.0, category: 'Anesthesia' },
      { name: 'Surgical Facility Fee Tier 3', code: '00100', statedPrice: 4500.0, negotiatedPrice: 1400.0, category: 'Facility' },
    ],
  },
  {
    id: 'sample-3',
    title: 'Cardiology Diagnostic Suite',
    hospital: 'Metro University Heart Center',
    insurance: 'UnitedHealthcare Choice Plus',
    isUnclear: false,
    description: 'Cardiopulmonary stress testing with comprehensive echocardiogram screening.',
    procedures: [
      { name: 'Transthoracic Echocardiogram Complete (CPT 93306)', code: '93306', statedPrice: 2850.0, negotiatedPrice: 720.0, category: 'Cardiology' },
      { name: 'Cardiovascular Stress Test (CPT 93015)', code: '93015', statedPrice: 1250.0, negotiatedPrice: 340.0, category: 'Diagnostic' },
      { name: 'Lipid Panel Biomarker Screen (CPT 80061)', code: '80061', statedPrice: 220.0, negotiatedPrice: 45.0, category: 'Lab' },
    ],
  },
];

export default function App() {
  const [activeTab, setActiveTab] = useState<'pipeline' | 'code' | 'database' | 'structure' | 'schemas'>('pipeline');
  const [entryMode, setEntryMode] = useState<'image' | 'manual'>('image');
  const [selectedSampleIndex, setSelectedSampleIndex] = useState<number>(0);
  const [copiedCode, setCopiedCode] = useState<boolean>(false);
  const [codeTab, setCodeTab] = useState<'main' | 'calculator' | 'query' | 'loader' | 'gemini' | 'schema'>('calculator');
  const [selectedJsonView, setSelectedJsonView] = useState<'final' | 'initial' | 'confirm_prompt'>('final');

  // Name match confirmation state
  const [confirmedProcedures, setConfirmedProcedures] = useState<Record<string, boolean>>({});

  // Manual entry custom bill state
  const [manualHospital, setManualHospital] = useState<string>('Mercy General Hospital');
  const [manualInsurance, setManualInsurance] = useState<string>('Blue Cross Blue Shield');
  const [manualProcedures, setManualProcedures] = useState<Array<{ name: string; code: string; statedPrice: number }>>([
    { name: 'Emergency Room Visit Level 4', code: '99284', statedPrice: 1850.0 },
    { name: 'Chest X-Ray 2-View', code: '71046', statedPrice: 580.0 },
  ]);

  const currentSample = SAMPLE_BILLS[selectedSampleIndex];

  // Active procedures based on entry mode
  const activeHospital = entryMode === 'manual' ? manualHospital : (currentSample.hospital || 'Unknown Hospital');
  const activeInsurance = entryMode === 'manual' ? manualInsurance : (currentSample.insurance || 'Self-Pay');

  const activeProcedures = entryMode === 'manual'
    ? manualProcedures.map((p) => ({
        name: p.name,
        code: p.code || null,
        statedPrice: p.statedPrice,
        negotiatedPrice: p.code === '99284' ? 620.0 : p.code === '71046' ? 145.0 : Math.round(p.statedPrice * 0.35),
        category: 'Custom Entry',
      }))
    : currentSample.procedures;

  // Detect if any procedure in active set was matched by name instead of code
  const proceduresRequiringConfirmation = activeProcedures.filter(
    (p) => (!p.code || p.code === '') && p.name && !confirmedProcedures[p.name]
  );

  const initialTotal = activeProcedures.reduce((sum, p) => sum + (p.statedPrice || 0), 0);
  const negotiatedTotal = activeProcedures.reduce((sum, p) => sum + (p.negotiatedPrice || 0), 0);
  const totalSavings = initialTotal - negotiatedTotal;
  const savingsPct = initialTotal > 0 ? Math.round((totalSavings / initialTotal) * 100) : 0;

  // JSON representations matching user specifications:
  // 1. userJson: { hospital, insurance company, patientProcedures: [{name, code, statedPrice}] }
  const userJsonData = {
    hospital: activeHospital,
    'insurance company': activeInsurance,
    patientProcedures: activeProcedures.map((p) => ({
      name: p.name,
      code: p.code,
      statedPrice: p.statedPrice,
    })),
  };

  // 2. finalbilljson: { hospital, insurance company, initialTotalBill, negotiatedFinalTotalBill, [proc]: {code, initialPrice, negotiatedPrice} }
  // (calculatedPrice and userinfo removed as requested)
  const finalBillJsonData: any = {
    hospital: activeHospital,
    'insurance company': activeInsurance,
    initialTotalBill: Number(initialTotal.toFixed(2)),
    negotiatedFinalTotalBill: Number(negotiatedTotal.toFixed(2)),
    finalTotalBill: Number(negotiatedTotal.toFixed(2)),
  };

  activeProcedures.forEach((p) => {
    if (p.name) {
      finalBillJsonData[p.name] = {
        code: p.code || '29881',
        initialPrice: Number((p.statedPrice || 0).toFixed(2)),
        negotiatedPrice: Number((p.negotiatedPrice || 0).toFixed(2)),
      };
    }
  });

  const confirmPromptPayload = {
    status: 'requires_procedure_confirmation',
    message: 'Some procedures could not be matched by code, but matching procedures were found by name. Please confirm if these match.',
    confirmations: proceduresRequiringConfirmation.map((p) => ({
      procedure_name: p.name,
      matched_name: `${p.name} (CPT 29881)`,
      matched_code: '29881',
      negotiated_price: p.negotiatedPrice,
      question: `Is '${p.name} (CPT 29881)' what you meant by '${p.name}'?`,
    })),
    userJson: userJsonData,
  };

  // Code snippets for viewer
  const mainPyCode = `# /backend/main.py
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import loader
import Gemini
import Calculator
from fastapi import FastAPI, UploadFile, File, HTTPException, Body
from schema import UserJson

# loader.py runs at startup scanning backend/database/<hospital_name>/<insurance>.json
loader.load_hospital_database()

app = FastAPI(title="Medical Bill Scanner API")

@app.post("/scan-bill")
async def scan_medical_bill(imageinput: UploadFile = File(...)):
    Img = await imageinput.read()
    userJson: UserJson = Gemini.extract_bill_info(Img)

    # If any field is unclear, Gemini sets it to null
    if userJson.has_null_fields():
        return {
            "status": "requires_manual_entry_or_reupload",
            "message": "Some fields could not be clearly read. Please re-upload or enter manually.",
            "null_fields": userJson.get_null_fields(),
            "userJson": userJson.to_user_dict()
        }

    # Calculator queries code first, then name
    finalbilljson, pending_confirmations = Calculator.calculate_final_bill(userJson)
    if pending_confirmations:
        return {
            "status": "requires_procedure_confirmation",
            "confirmations": pending_confirmations,
            "finalbilljson": finalbilljson
        }

    return {"status": "success", "finalbilljson": finalbilljson}

# Option for user to forgo uploading image and fill in fields manually
@app.post("/manual-bill")
def manual_bill(manual_user_json: dict = Body(...)):
    userJson = UserJson(**manual_user_json)
    finalbilljson, pending_confirmations = Calculator.calculate_final_bill(userJson)
    if pending_confirmations:
        return {
            "status": "requires_procedure_confirmation",
            "confirmations": pending_confirmations,
            "finalbilljson": finalbilljson
        }
    return {"status": "success", "finalbilljson": finalbilljson}

@app.post("/confirm-procedures")
def confirm_procedures(payload: dict = Body(...)):
    userJson = UserJson(**payload.get("userJson", {}))
    finalbilljson, _ = Calculator.calculate_final_bill(userJson, payload.get("confirmed_procedures", {}))
    return {"status": "success", "finalbilljson": finalbilljson}`;

  const calculatorPyCode = `# /backend/Calculator.py
from schema.models import UserJson
import query

def calculate_final_bill(user_json_input, user_confirmed_procedures=None):
    user_json = user_json_input if isinstance(user_json_input, UserJson) else UserJson(**user_json_input)
    hospital = user_json.hospital or "Unknown Hospital"
    insurance = user_json.insurance_company or "Self-Pay"
    user_confirmed_procedures = user_confirmed_procedures or {}

    initial_total = 0.0
    negotiated_final_total = 0.0
    pending_confirmations = []

    # Note: userinfo and calculatedPrice have been removed from finalbilljson
    finalbilljson = {
        "hospital": hospital,
        "insurance company": insurance,
    }

    for proc in user_json.patientProcedures:
        stated = float(proc.statedPrice or 0.0)
        initial_total += stated
        proc_name = proc.name or f"Procedure {proc.code or 'Unknown'}"

        # Query DuckDB: code first, then name
        match_result = query.query_procedure(
            hospital=hospital,
            insurance_company=insurance,
            procedure_code=proc.code,
            procedure_name=proc_name,
            stated_price=stated,
        )

        negotiated_price = float(match_result["negotiated_price"])
        effective_code = proc.code or match_result.get("matched_code")

        # If matched by name, ask user to confirm
        if match_result.get("needs_user_confirmation") and not user_confirmed_procedures.get(proc_name):
            pending_confirmations.append({
                "procedure_name": proc_name,
                "matched_name": match_result.get("matched_procedure_name"),
                "matched_code": match_result.get("matched_code"),
                "negotiated_price": negotiated_price,
                "question": f"Is '{match_result.get('matched_procedure_name')}' what you meant by '{proc_name}'?"
            })

        negotiated_final_total += negotiated_price

        # Record breakdown with code, initialPrice, negotiatedPrice (NO calculatedPrice)
        finalbilljson[proc_name] = {
            "code": effective_code,
            "initialPrice": round(stated, 2),
            "negotiatedPrice": round(negotiated_price, 2),
        }

    finalbilljson["initialTotalBill"] = round(initial_total, 2)
    finalbilljson["negotiatedFinalTotalBill"] = round(negotiated_final_total, 2)
    finalbilljson["finalTotalBill"] = round(negotiated_final_total, 2)

    return finalbilljson, pending_confirmations`;

  const queryPyCode = `# /backend/query.py
import duckdb

def query_procedure(hospital, insurance_company, procedure_code=None, procedure_name=None, stated_price=0.0):
    conn = get_db_connection()
    safe_stated = float(stated_price or 0.0)

    # 1. First: Query with procedure CODE
    if procedure_code:
        row = conn.execute("""
            SELECT negotiated_price, procedure_name, code FROM hospital_payer_rates
            WHERE LOWER(hospital) = LOWER(?) AND LOWER(insurance_company) = LOWER(?) AND LOWER(code) = LOWER(?)
            LIMIT 1;
        """, [hospital, insurance_company, procedure_code]).fetchone()
        if row:
            return {
                "negotiated_price": float(row[0]),
                "matched_by": "code",
                "matched_code": row[2],
                "matched_procedure_name": row[1],
                "needs_user_confirmation": False
            }

    # 2. Second: If not found with code, query with procedure NAME
    if procedure_name:
        row = conn.execute("""
            SELECT negotiated_price, procedure_name, code FROM hospital_payer_rates
            WHERE LOWER(hospital) = LOWER(?) AND LOWER(insurance_company) = LOWER(?)
              AND (LOWER(?) LIKE '%' || LOWER(procedure_name) || '%' OR LOWER(procedure_name) LIKE '%' || LOWER(?) || '%')
            LIMIT 1;
        """, [hospital, insurance_company, procedure_name, procedure_name]).fetchone()
        if row:
            # Flags needs_user_confirmation=True to prompt user
            return {
                "negotiated_price": float(row[0]),
                "matched_by": "name",
                "matched_code": row[2],
                "matched_procedure_name": row[1],
                "needs_user_confirmation": True
            }

    return {"negotiated_price": round(safe_stated * 0.35, 2), "matched_by": "benchmark", "needs_user_confirmation": False}`;

  const loaderPyCode = `# /backend/loader.py
import os
import json
import query

def load_hospital_database(database_dir=None):
    if database_dir is None:
        database_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database")
    
    total_loaded = 0
    # Scans hospital folders in backend/database/
    for hospital_folder in os.listdir(database_dir):
        hospital_path = os.path.join(database_dir, hospital_folder)
        if os.path.isdir(hospital_path):
            # Loads JSON files named after insurance company (e.g. blue_cross_blue_shield.json, aetna.json)
            for json_file in os.listdir(hospital_path):
                if json_file.endswith(".json"):
                    with open(os.path.join(hospital_path, json_file)) as f:
                        records = json.load(f)
                        inserted = query.insert_hospital_rates(records)
                        total_loaded += inserted
                        print(f"Loaded {inserted} rates from {hospital_folder}/{json_file}")
    return total_loaded`;

  const geminiPyCode = `# /backend/Gemini.py
import os
from schema import UserJson

BILL_EXTRACTION_PROMPT = """Analyze this medical bill image. Extract in strict JSON:
1. "hospital": Healthcare facility name (or null if unclear)
2. "insurance company": Patient insurance provider (or null if unclear)
3. "patientProcedures": Array of {
     "name": Procedure description (or null if unclear),
     "code": CPT or HCPCS code (or null if unclear),
     "statedPrice": Numeric charge (or null if unclear)
   }

CRITICAL: If any field is unclear, blurred, or unreadable, set it to null."""

def extract_bill_info(imageinput) -> UserJson:
    # Model extracts fields using multimodal vision
    # Unclear fields are set to null`;

  const modelsPyCode = `# /backend/schema/models.py
from typing import List, Optional
from pydantic import BaseModel, Field

class PatientProcedureStated(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    statedPrice: Optional[float] = None

class UserJson(BaseModel):
    hospital: Optional[str] = None
    insurance_company: Optional[str] = Field(None, alias="insurance company")
    patientProcedures: List[PatientProcedureStated] = []

class FinalBillJson(BaseModel):
    hospital: str
    insurance_company: str
    initialTotalBill: float
    negotiatedFinalTotalBill: float
    # calculatedPrice and userinfo removed
    # procedure breakdowns contain: {code, initialPrice, negotiatedPrice}`;

  const copyToClipboard = () => {
    const codeMap = {
      main: mainPyCode,
      calculator: calculatorPyCode,
      query: queryPyCode,
      loader: loaderPyCode,
      gemini: geminiPyCode,
      schema: modelsPyCode,
    };
    navigator.clipboard.writeText(codeMap[codeTab]);
    setCopiedCode(true);
    setTimeout(() => setCopiedCode(false), 2000);
  };

  const handleAddManualProcedure = () => {
    setManualProcedures([
      ...manualProcedures,
      { name: 'New Procedure', code: '', statedPrice: 500.0 },
    ]);
  };

  const handleRemoveManualProcedure = (index: number) => {
    setManualProcedures(manualProcedures.filter((_, i) => i !== index));
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      {/* Top Header */}
      <header className="border-b border-slate-800 bg-slate-900/70 backdrop-blur sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-emerald-500 to-teal-400 flex items-center justify-center shadow-lg shadow-emerald-500/20">
              <DollarSign className="w-6 h-6 text-slate-950 stroke-[2.5]" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-lg font-bold text-white tracking-tight">BillAudit AI</h1>
                <span className="text-[11px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                  /backend & /frontend Organized
                </span>
              </div>
              <p className="text-xs text-slate-400">Medical Bill Savings Scanner with Code-First Query & Hospital Folders</p>
            </div>
          </div>

          {/* Navigation Tabs */}
          <div className="flex items-center gap-1 bg-slate-800/80 p-1 rounded-lg border border-slate-700/60 text-xs font-medium">
            <button
              onClick={() => setActiveTab('pipeline')}
              className={`px-3 py-1.5 rounded-md transition-all flex items-center gap-1.5 ${
                activeTab === 'pipeline'
                  ? 'bg-emerald-500 text-slate-950 font-semibold shadow'
                  : 'text-slate-300 hover:text-white hover:bg-slate-700/50'
              }`}
            >
              <TrendingDown className="w-3.5 h-3.5" />
              Pipeline & Audit
            </button>
            <button
              onClick={() => setActiveTab('code')}
              className={`px-3 py-1.5 rounded-md transition-all flex items-center gap-1.5 ${
                activeTab === 'code'
                  ? 'bg-emerald-500 text-slate-950 font-semibold shadow'
                  : 'text-slate-300 hover:text-white hover:bg-slate-700/50'
              }`}
            >
              <Code2 className="w-3.5 h-3.5" />
              Backend Code
            </button>
            <button
              onClick={() => setActiveTab('database')}
              className={`px-3 py-1.5 rounded-md transition-all flex items-center gap-1.5 ${
                activeTab === 'database'
                  ? 'bg-emerald-500 text-slate-950 font-semibold shadow'
                  : 'text-slate-300 hover:text-white hover:bg-slate-700/50'
              }`}
            >
              <FolderTree className="w-3.5 h-3.5" />
              Hospital Folders DB
            </button>
            <button
              onClick={() => setActiveTab('structure')}
              className={`px-3 py-1.5 rounded-md transition-all flex items-center gap-1.5 ${
                activeTab === 'structure'
                  ? 'bg-emerald-500 text-slate-950 font-semibold shadow'
                  : 'text-slate-300 hover:text-white hover:bg-slate-700/50'
              }`}
            >
              <FolderCode className="w-3.5 h-3.5" />
              Project Structure
            </button>
            <button
              onClick={() => setActiveTab('schemas')}
              className={`px-3 py-1.5 rounded-md transition-all flex items-center gap-1.5 ${
                activeTab === 'schemas'
                  ? 'bg-emerald-500 text-slate-950 font-semibold shadow'
                  : 'text-slate-300 hover:text-white hover:bg-slate-700/50'
              }`}
            >
              <Layers className="w-3.5 h-3.5" />
              JSON Specs
            </button>
          </div>
        </div>
      </header>

      {/* Main Content Area */}
      <main className="flex-1 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 w-full">
        {activeTab === 'pipeline' && (
          <div className="space-y-8">
            {/* Entry Mode Toggle Header */}
            <div className="bg-slate-900 border border-slate-800 rounded-2xl p-4 flex flex-wrap items-center justify-between gap-4">
              <div>
                <h2 className="text-sm font-bold text-white flex items-center gap-2">
                  <Sparkles className="w-4 h-4 text-emerald-400" />
                  Select Input Method:
                </h2>
                <p className="text-xs text-slate-400 mt-0.5">
                  Scan a photo with Gemini or forgo uploading an image and enter bill details manually.
                </p>
              </div>

              <div className="flex items-center gap-2 bg-slate-800/80 p-1 rounded-xl border border-slate-700">
                <button
                  onClick={() => setEntryMode('image')}
                  className={`px-3.5 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition ${
                    entryMode === 'image'
                      ? 'bg-emerald-500 text-slate-950 shadow'
                      : 'text-slate-300 hover:text-white'
                  }`}
                >
                  <Camera className="w-3.5 h-3.5" />
                  Scan Bill Image (/scan-bill)
                </button>
                <button
                  onClick={() => setEntryMode('manual')}
                  className={`px-3.5 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition ${
                    entryMode === 'manual'
                      ? 'bg-emerald-500 text-slate-950 shadow'
                      : 'text-slate-300 hover:text-white'
                  }`}
                >
                  <Edit3 className="w-3.5 h-3.5" />
                  Forgo Image & Fill Manually (/manual-bill)
                </button>
              </div>
            </div>

            {/* If Manual Entry Mode is selected */}
            {entryMode === 'manual' && (
              <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-xl space-y-5">
                <div className="flex items-center justify-between border-b border-slate-800 pb-4">
                  <div>
                    <h3 className="text-base font-bold text-white flex items-center gap-2">
                      <Edit3 className="w-4 h-4 text-emerald-400" />
                      Manual Medical Bill Builder (/manual-bill)
                    </h3>
                    <p className="text-xs text-slate-400 mt-1">
                      Skip OCR photo upload and directly input hospital charges to compare against DuckDB negotiated rates.
                    </p>
                  </div>
                  <span className="text-[11px] font-mono text-emerald-400 bg-emerald-950/60 border border-emerald-800/60 px-2.5 py-1 rounded-lg">
                    Direct Pydantic UserJson Input
                  </span>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs font-semibold text-slate-300 mb-1">Hospital / Medical Center</label>
                    <input
                      type="text"
                      value={manualHospital}
                      onChange={(e) => setManualHospital(e.target.value)}
                      className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white font-mono focus:border-emerald-500 focus:outline-none"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-slate-300 mb-1">Insurance Company / Payer</label>
                    <input
                      type="text"
                      value={manualInsurance}
                      onChange={(e) => setManualInsurance(e.target.value)}
                      className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white font-mono focus:border-emerald-500 focus:outline-none"
                    />
                  </div>
                </div>

                {/* Procedure line items editor */}
                <div>
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-semibold text-slate-300">Bill Procedures & Charges</span>
                    <button
                      onClick={handleAddManualProcedure}
                      className="text-xs bg-slate-800 hover:bg-slate-750 text-emerald-400 font-semibold px-2.5 py-1 rounded-md border border-slate-700 flex items-center gap-1 transition"
                    >
                      <Plus className="w-3.5 h-3.5" />
                      Add Procedure
                    </button>
                  </div>

                  <div className="space-y-2">
                    {manualProcedures.map((proc, idx) => (
                      <div key={idx} className="grid grid-cols-12 gap-2 bg-slate-850 p-2.5 rounded-lg border border-slate-800 items-center text-xs">
                        <div className="col-span-6">
                          <input
                            type="text"
                            value={proc.name}
                            onChange={(e) => {
                              const updated = [...manualProcedures];
                              updated[idx].name = e.target.value;
                              setManualProcedures(updated);
                            }}
                            placeholder="Procedure Description"
                            className="w-full bg-slate-800 border border-slate-700 rounded px-2.5 py-1.5 text-white focus:outline-none focus:border-emerald-500"
                          />
                        </div>
                        <div className="col-span-3">
                          <input
                            type="text"
                            value={proc.code}
                            onChange={(e) => {
                              const updated = [...manualProcedures];
                              updated[idx].code = e.target.value;
                              setManualProcedures(updated);
                            }}
                            placeholder="CPT Code (e.g. 99284)"
                            className="w-full bg-slate-800 border border-slate-700 rounded px-2.5 py-1.5 text-white font-mono focus:outline-none focus:border-emerald-500"
                          />
                        </div>
                        <div className="col-span-2">
                          <input
                            type="number"
                            value={proc.statedPrice}
                            onChange={(e) => {
                              const updated = [...manualProcedures];
                              updated[idx].statedPrice = parseFloat(e.target.value) || 0;
                              setManualProcedures(updated);
                            }}
                            placeholder="Price ($)"
                            className="w-full bg-slate-800 border border-slate-700 rounded px-2.5 py-1.5 text-white font-mono focus:outline-none focus:border-emerald-500"
                          />
                        </div>
                        <div className="col-span-1 flex justify-center">
                          <button
                            onClick={() => handleRemoveManualProcedure(idx)}
                            className="text-slate-400 hover:text-rose-400 transition"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {/* 2-Stage Query Confirmation Banner (Code Not Found -> Name Found -> User Asked to Confirm) */}
            {proceduresRequiringConfirmation.length > 0 && (
              <div className="bg-amber-950/40 border-2 border-amber-500/60 rounded-2xl p-5 shadow-xl space-y-3 animate-in fade-in">
                <div className="flex items-start gap-3">
                  <div className="w-9 h-9 rounded-xl bg-amber-500/20 text-amber-400 flex items-center justify-center shrink-0 border border-amber-500/30">
                    <HelpCircle className="w-5 h-5" />
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <h4 className="text-sm font-bold text-white">Procedure Match Confirmation Required</h4>
                      <span className="text-[10px] font-mono bg-amber-500/20 text-amber-300 px-2 py-0.5 rounded border border-amber-500/30">
                        backend/query.py: matched_by = 'name'
                      </span>
                    </div>
                    <p className="text-xs text-slate-300 mt-1">
                      We queried DuckDB with the procedure code first, but no code was found. We then queried by procedure name.
                      Please confirm if the matched hospital procedure is what was meant:
                    </p>

                    <div className="mt-3 space-y-2">
                      {proceduresRequiringConfirmation.map((proc, i) => (
                        <div key={i} className="bg-slate-900/90 p-3 rounded-xl border border-amber-500/30 flex flex-wrap items-center justify-between gap-3 text-xs">
                          <div>
                            <span className="text-slate-400 block text-[11px]">Your Bill Line:</span>
                            <span className="text-white font-semibold">{proc.name}</span>
                            <span className="text-slate-400 block text-[11px] mt-1">
                              Matched in DuckDB under {activeHospital}:{' '}
                              <strong className="text-emerald-400">{proc.name} (CPT 29881)</strong>
                            </span>
                          </div>

                          <div className="flex items-center gap-2">
                            <button
                              onClick={() => {
                                setConfirmedProcedures({
                                  ...confirmedProcedures,
                                  [proc.name || '']: true,
                                });
                              }}
                              className="bg-emerald-500 hover:bg-emerald-400 text-slate-950 font-bold px-3 py-1.5 rounded-lg flex items-center gap-1 shadow transition text-xs"
                            >
                              <CheckCheck className="w-3.5 h-3.5" />
                              Yes, Confirm Match
                            </button>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Bill Selector & Audit Result Grid */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              {/* Left Column: Sample Bill Picker & Metadata */}
              <div className="lg:col-span-1 space-y-4">
                <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm">
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-sm font-semibold text-white flex items-center gap-2">
                      <FileText className="w-4 h-4 text-emerald-400" />
                      Select Bill Test Case
                    </h3>
                    <span className="text-xs text-slate-500 font-mono">Input</span>
                  </div>

                  <div className="space-y-2.5">
                    {SAMPLE_BILLS.map((sample, idx) => (
                      <button
                        key={idx}
                        onClick={() => {
                          setSelectedSampleIndex(idx);
                          setConfirmedProcedures({});
                        }}
                        className={`w-full text-left p-3 rounded-lg border transition-all ${
                          selectedSampleIndex === idx && entryMode === 'image'
                            ? 'bg-emerald-950/30 border-emerald-500 text-white shadow-sm'
                            : 'bg-slate-800/40 border-slate-800 text-slate-300 hover:bg-slate-800 hover:border-slate-700'
                        }`}
                      >
                        <div className="font-semibold text-xs flex items-center justify-between">
                          <span>{sample.title}</span>
                          {selectedSampleIndex === idx && entryMode === 'image' && (
                            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                          )}
                        </div>
                        <div className="text-[11px] text-emerald-400/90 font-medium mt-0.5">{sample.hospital}</div>
                        <div className="text-[11px] text-slate-400 mt-1 line-clamp-1">{sample.description}</div>
                      </button>
                    ))}
                  </div>

                  {/* Summary Metric Cards */}
                  <div className="mt-5 pt-5 border-t border-slate-800 space-y-3">
                    <div className="p-3 rounded-lg bg-slate-800/60 border border-slate-750 flex items-center justify-between">
                      <div>
                        <div className="text-[11px] text-slate-400">Total Billed (initialTotalBill)</div>
                        <div className="text-base font-bold text-slate-200">${initialTotal.toLocaleString()}</div>
                      </div>
                      <AlertTriangle className="w-5 h-5 text-amber-400/80" />
                    </div>

                    <div className="p-3 rounded-lg bg-emerald-950/30 border border-emerald-800/40 flex items-center justify-between">
                      <div>
                        <div className="text-[11px] text-emerald-400 font-medium">negotiatedFinalTotalBill</div>
                        <div className="text-base font-bold text-white">${negotiatedTotal.toLocaleString()}</div>
                      </div>
                      <ShieldCheck className="w-5 h-5 text-emerald-400" />
                    </div>

                    <div className="p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-between">
                      <div>
                        <div className="text-[11px] text-emerald-300 font-medium">Potential Patient Savings</div>
                        <div className="text-lg font-black text-emerald-400">
                          ${totalSavings.toLocaleString()}{' '}
                          <span className="text-xs font-semibold text-emerald-300/80">({savingsPct}%)</span>
                        </div>
                      </div>
                      <TrendingDown className="w-6 h-6 text-emerald-400" />
                    </div>
                  </div>
                </div>

                {/* Query strategy info */}
                <div className="bg-slate-900/60 border border-slate-800/80 rounded-xl p-4 text-xs text-slate-400 flex items-start gap-3">
                  <Database className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                  <p className="leading-relaxed">
                    <strong className="text-slate-200">Query Strategy:</strong> DuckDB searches by CPT code first. If absent or unmatched, it searches by procedure description and prompts the user to verify the match before billing.
                  </p>
                </div>
              </div>

              {/* Right Column: Line Item Error & Discrepancy Breakdown */}
              <div className="lg:col-span-2 space-y-4">
                <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
                  <div className="p-5 border-b border-slate-800 flex flex-wrap items-center justify-between gap-4">
                    <div>
                      <h3 className="text-sm font-semibold text-white">Line-Item Pricing Audit</h3>
                      <p className="text-xs text-slate-400 mt-0.5">
                        Format: <code className="text-emerald-400 font-mono">&#123;code, initialPrice, negotiatedPrice&#125;</code>{' '}
                        (<span className="text-rose-400 line-through">calculatedPrice</span> and{' '}
                        <span className="text-rose-400 line-through">userinfo</span> removed)
                      </p>
                    </div>

                    <div className="flex items-center gap-2">
                      <span className="text-xs text-slate-400">Payer:</span>
                      <span className="text-xs font-medium text-slate-200 bg-slate-800 px-2 py-0.5 rounded border border-slate-700">
                        {activeInsurance}
                      </span>
                    </div>
                  </div>

                  {/* Procedures Table */}
                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-xs">
                      <thead className="bg-slate-855 text-slate-400 font-semibold uppercase tracking-wider text-[10px] border-b border-slate-800">
                        <tr>
                          <th className="py-3 px-4">Code</th>
                          <th className="py-3 px-4">Procedure Description</th>
                          <th className="py-3 px-4 text-right">initialPrice</th>
                          <th className="py-3 px-4 text-right">negotiatedPrice</th>
                          <th className="py-3 px-4 text-right">Discrepancy / Savings</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-800/70">
                        {activeProcedures.map((proc, i) => {
                          const stated = proc.statedPrice || 0;
                          const negotiated = proc.negotiatedPrice || 0;
                          const diff = stated - negotiated;
                          const diffPct = stated > 0 ? Math.round((diff / stated) * 100) : 0;
                          const isNameMatched = !proc.code && proc.name;

                          return (
                            <tr key={i} className="hover:bg-slate-800/40 transition-colors">
                              <td className="py-3.5 px-4 font-mono font-bold">
                                {proc.code ? (
                                  <span className="text-emerald-400 bg-emerald-950/60 border border-emerald-800/50 px-2 py-0.5 rounded">
                                    {proc.code}
                                  </span>
                                ) : (
                                  <span className="text-amber-400 bg-amber-950/50 border border-amber-800/50 px-1.5 py-0.5 rounded text-[11px]">
                                    name-matched
                                  </span>
                                )}
                              </td>
                              <td className="py-3.5 px-4 font-medium text-slate-200">
                                <div>{proc.name}</div>
                                {isNameMatched && (
                                  <span className="text-[10px] text-amber-400 font-sans mt-0.5 block">
                                    Confirmed match via description search
                                  </span>
                                )}
                              </td>
                              <td className="py-3.5 px-4 text-right font-mono font-medium text-slate-300">
                                ${stated.toFixed(2)}
                              </td>
                              <td className="py-3.5 px-4 text-right font-mono text-emerald-400 font-semibold">
                                ${negotiated.toFixed(2)}
                              </td>
                              <td className="py-3.5 px-4 text-right">
                                <span className="inline-flex items-center gap-1 font-mono text-emerald-400 font-bold bg-emerald-950/40 border border-emerald-800/50 px-2 py-0.5 rounded">
                                  -${diff.toFixed(2)} ({diffPct}%)
                                </span>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>

                  {/* Totals Footer */}
                  <div className="bg-slate-850 p-4 border-t border-slate-800 flex items-center justify-between text-xs">
                    <span className="text-slate-400 font-medium">initialTotalBill vs. negotiatedFinalTotalBill:</span>
                    <div className="flex items-center gap-4">
                      <span className="text-slate-400 line-through font-mono">${initialTotal.toFixed(2)}</span>
                      <ArrowRight className="w-3.5 h-3.5 text-slate-500" />
                      <span className="text-emerald-400 font-bold font-mono text-sm">${negotiatedTotal.toFixed(2)}</span>
                    </div>
                  </div>
                </div>

                {/* Status Callout */}
                <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 text-xs flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <ShieldCheck className="w-4 h-4 text-emerald-400" />
                    <span className="text-slate-300">
                      Calculated from DuckDB hospital subdirectories in <code className="text-emerald-400 font-mono">backend/database/</code>.
                    </span>
                  </div>
                  <span className="font-mono text-[11px] text-slate-400">
                    calculatedPrice removed | userinfo removed
                  </span>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Tab 2: Backend Code Viewer */}
        {activeTab === 'code' && (
          <div className="space-y-6">
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm flex items-center justify-between">
              <div>
                <h3 className="text-base font-bold text-white flex items-center gap-2">
                  <Code2 className="w-4 h-4 text-emerald-400" />
                  Backend Python Modules (/backend)
                </h3>
                <p className="text-xs text-slate-400 mt-0.5">
                  All backend Python code organized into <code className="text-emerald-400">/backend</code> folder.
                </p>
              </div>

              <span className="text-xs font-mono bg-slate-800 text-slate-300 px-3 py-1 rounded-full border border-slate-700">
                Python 3.10+
              </span>
            </div>

            {/* Code Viewer with Tabs */}
            <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
              <div className="bg-slate-850 p-4 border-b border-slate-800 flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  <div className="flex gap-1.5">
                    <span className="w-3 h-3 rounded-full bg-rose-500/80 inline-block"></span>
                    <span className="w-3 h-3 rounded-full bg-amber-500/80 inline-block"></span>
                    <span className="w-3 h-3 rounded-full bg-emerald-500/80 inline-block"></span>
                  </div>
                  <div className="flex items-center gap-1 bg-slate-900/80 p-1 rounded-lg border border-slate-800 text-xs flex-wrap">
                    <button
                      onClick={() => setCodeTab('main')}
                      className={`px-2.5 py-1 rounded-md font-mono transition ${
                        codeTab === 'main'
                          ? 'bg-emerald-500 text-slate-950 font-bold shadow'
                          : 'text-slate-400 hover:text-white'
                      }`}
                    >
                      backend/main.py
                    </button>
                    <button
                      onClick={() => setCodeTab('calculator')}
                      className={`px-2.5 py-1 rounded-md font-mono transition ${
                        codeTab === 'calculator'
                          ? 'bg-emerald-500 text-slate-950 font-bold shadow'
                          : 'text-slate-400 hover:text-white'
                      }`}
                    >
                      backend/Calculator.py
                    </button>
                    <button
                      onClick={() => setCodeTab('query')}
                      className={`px-2.5 py-1 rounded-md font-mono transition ${
                        codeTab === 'query'
                          ? 'bg-emerald-500 text-slate-950 font-bold shadow'
                          : 'text-slate-400 hover:text-white'
                      }`}
                    >
                      backend/query.py
                    </button>
                    <button
                      onClick={() => setCodeTab('loader')}
                      className={`px-2.5 py-1 rounded-md font-mono transition ${
                        codeTab === 'loader'
                          ? 'bg-emerald-500 text-slate-950 font-bold shadow'
                          : 'text-slate-400 hover:text-white'
                      }`}
                    >
                      backend/loader.py
                    </button>
                    <button
                      onClick={() => setCodeTab('gemini')}
                      className={`px-2.5 py-1 rounded-md font-mono transition ${
                        codeTab === 'gemini'
                          ? 'bg-emerald-500 text-slate-950 font-bold shadow'
                          : 'text-slate-400 hover:text-white'
                      }`}
                    >
                      backend/Gemini.py
                    </button>
                    <button
                      onClick={() => setCodeTab('schema')}
                      className={`px-2.5 py-1 rounded-md font-mono transition ${
                        codeTab === 'schema'
                          ? 'bg-emerald-500 text-slate-950 font-bold shadow'
                          : 'text-slate-400 hover:text-white'
                      }`}
                    >
                      backend/schema/models.py
                    </button>
                  </div>
                </div>

                <button
                  onClick={copyToClipboard}
                  className="flex items-center gap-1.5 text-xs font-medium text-slate-300 hover:text-white bg-slate-800 hover:bg-slate-750 px-3 py-1.5 rounded-lg border border-slate-700 transition"
                >
                  {copiedCode ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                  {copiedCode ? 'Copied!' : `Copy ${codeTab}.py`}
                </button>
              </div>

              <div className="p-4 bg-slate-950/90 font-mono text-xs text-slate-300 overflow-x-auto leading-relaxed max-h-[600px]">
                <pre>
                  {codeTab === 'main'
                    ? mainPyCode
                    : codeTab === 'calculator'
                    ? calculatorPyCode
                    : codeTab === 'query'
                    ? queryPyCode
                    : codeTab === 'loader'
                    ? loaderPyCode
                    : codeTab === 'gemini'
                    ? geminiPyCode
                    : modelsPyCode}
                </pre>
              </div>
            </div>
          </div>
        )}

        {/* Tab 3: database/<hospital_folder>/ Hierarchy Explorer */}
        {activeTab === 'database' && (
          <div className="space-y-6">
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h3 className="text-base font-bold text-white flex items-center gap-2">
                    <FolderTree className="w-4 h-4 text-emerald-400" />
                    backend/database/&lt;hospital_folder&gt;/&lt;insurance&gt;.json Architecture
                  </h3>
                  <p className="text-xs text-slate-400 mt-1">
                    Multiple hospital folders, each named after the hospital, containing JSON files named after the insurance companies.
                  </p>
                </div>
                <span className="text-xs font-mono bg-emerald-950/60 text-emerald-400 border border-emerald-800 px-3 py-1 rounded-full">
                  15 Total Rates Loaded
                </span>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-4">
                <div className="p-4 rounded-xl bg-slate-850 border border-slate-800 space-y-3">
                  <div className="flex items-center gap-2 text-white font-bold text-xs border-b border-slate-800 pb-2">
                    <FolderTree className="w-4 h-4 text-emerald-400" />
                    backend/database/mercy_general_hospital/
                  </div>
                  <ul className="space-y-1.5 text-xs">
                    <li className="flex items-center justify-between p-2 rounded bg-slate-800/60 font-mono text-[11px]">
                      <span className="text-emerald-400">blue_cross_blue_shield.json</span>
                      <span className="text-slate-400">5 rates</span>
                    </li>
                    <li className="flex items-center justify-between p-2 rounded bg-slate-800/60 font-mono text-[11px]">
                      <span className="text-emerald-400">aetna.json</span>
                      <span className="text-slate-400">3 rates</span>
                    </li>
                  </ul>
                  <p className="text-[11px] text-slate-400">Includes ER Level 4 (99284), Abdominal CT (74177), Lab panel (80053), IV Hydration (96360), X-Ray (71046)</p>
                </div>

                <div className="p-4 rounded-xl bg-slate-850 border border-slate-800 space-y-3">
                  <div className="flex items-center gap-2 text-white font-bold text-xs border-b border-slate-800 pb-2">
                    <FolderTree className="w-4 h-4 text-emerald-400" />
                    backend/database/st_jude_specialty_hospital/
                  </div>
                  <ul className="space-y-1.5 text-xs">
                    <li className="flex items-center justify-between p-2 rounded bg-slate-800/60 font-mono text-[11px]">
                      <span className="text-emerald-400">aetna.json</span>
                      <span className="text-slate-400">4 rates</span>
                    </li>
                  </ul>
                  <p className="text-[11px] text-slate-400">Includes Knee Arthroscopy (29881), Anesthesia (01400), Facility fee (00100), Immobilizer (L1830)</p>
                </div>

                <div className="p-4 rounded-xl bg-slate-850 border border-slate-800 space-y-3">
                  <div className="flex items-center gap-2 text-white font-bold text-xs border-b border-slate-800 pb-2">
                    <FolderTree className="w-4 h-4 text-emerald-400" />
                    backend/database/metro_university_heart_center/
                  </div>
                  <ul className="space-y-1.5 text-xs">
                    <li className="flex items-center justify-between p-2 rounded bg-slate-800/60 font-mono text-[11px]">
                      <span className="text-emerald-400">unitedhealthcare.json</span>
                      <span className="text-slate-400">3 rates</span>
                    </li>
                  </ul>
                  <p className="text-[11px] text-slate-400">Includes Transthoracic Echocardiogram (93306), Cardiovascular Stress (93015), Lipid Panel (80061)</p>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Tab 4: Full Project Structure (/backend & /frontend) */}
        {activeTab === 'structure' && (
          <div className="space-y-6">
            <div className="bg-slate-900 border border-slate-800 rounded-xl p-6">
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h3 className="text-base font-bold text-white flex items-center gap-2">
                    <FolderCode className="w-5 h-5 text-emerald-400" />
                    Directory Layout: /backend and /frontend
                  </h3>
                  <p className="text-xs text-slate-400 mt-1">
                    Clean separation between Python backend services and TypeScript React frontend.
                  </p>
                </div>
                <span className="text-xs font-mono bg-emerald-950/60 text-emerald-400 border border-emerald-800 px-3 py-1 rounded-full">
                  Fully Organized
                </span>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-4">
                {/* Backend Structure Card */}
                <div className="p-5 rounded-xl bg-slate-850 border border-slate-800 space-y-4">
                  <div className="flex items-center gap-2 text-emerald-400 font-bold text-sm border-b border-slate-800 pb-3">
                    <Server className="w-4 h-4" />
                    /backend (Python, DuckDB & Gemini)
                  </div>
                  <div className="font-mono text-xs text-slate-300 space-y-1.5 bg-slate-900/90 p-4 rounded-lg border border-slate-800 leading-relaxed">
                    <div className="text-emerald-400 font-bold">backend/</div>
                    <div className="pl-4 text-slate-300">├── main.py <span className="text-slate-500 font-sans text-[11px]">(FastAPI server, endpoints)</span></div>
                    <div className="pl-4 text-slate-300">├── Calculator.py <span className="text-slate-500 font-sans text-[11px]">(Calculates negotiated total)</span></div>
                    <div className="pl-4 text-slate-300">├── query.py <span className="text-slate-500 font-sans text-[11px]">(Code-first & name DuckDB queries)</span></div>
                    <div className="pl-4 text-slate-300">├── loader.py <span className="text-slate-500 font-sans text-[11px]">(Loads hospital folders at startup)</span></div>
                    <div className="pl-4 text-slate-300">├── Gemini.py <span className="text-slate-500 font-sans text-[11px]">(Multimodal OCR vision parser)</span></div>
                    <div className="pl-4 text-slate-300">├── requirements.txt <span className="text-slate-500 font-sans text-[11px]">(FastAPI, DuckDB, Gemini)</span></div>
                    <div className="pl-4 text-slate-300">├── schema/</div>
                    <div className="pl-8 text-slate-300">├── __init__.py</div>
                    <div className="pl-8 text-slate-300">└── models.py <span className="text-slate-500 font-sans text-[11px]">(Pydantic schemas)</span></div>
                    <div className="pl-4 text-slate-300">└── database/ <span className="text-slate-500 font-sans text-[11px]">(Hospital folders)</span></div>
                    <div className="pl-8 text-slate-300">├── mercy_general_hospital/</div>
                    <div className="pl-12 text-slate-400">├── blue_cross_blue_shield.json</div>
                    <div className="pl-12 text-slate-400">└── aetna.json</div>
                    <div className="pl-8 text-slate-300">├── st_jude_specialty_hospital/</div>
                    <div className="pl-12 text-slate-400">└── aetna.json</div>
                    <div className="pl-8 text-slate-300">└── metro_university_heart_center/</div>
                    <div className="pl-12 text-slate-400">└── unitedhealthcare.json</div>
                  </div>
                </div>

                {/* Frontend Structure Card */}
                <div className="p-5 rounded-xl bg-slate-850 border border-slate-800 space-y-4">
                  <div className="flex items-center gap-2 text-cyan-400 font-bold text-sm border-b border-slate-800 pb-3">
                    <Monitor className="w-4 h-4" />
                    /frontend (React, Vite & Tailwind CSS)
                  </div>
                  <div className="font-mono text-xs text-slate-300 space-y-1.5 bg-slate-900/90 p-4 rounded-lg border border-slate-800 leading-relaxed">
                    <div className="text-cyan-400 font-bold">frontend/</div>
                    <div className="pl-4 text-slate-300">├── index.html <span className="text-slate-500 font-sans text-[11px]">(SPA HTML document entry)</span></div>
                    <div className="pl-4 text-slate-300">└── src/</div>
                    <div className="pl-8 text-slate-300">├── App.tsx <span className="text-slate-500 font-sans text-[11px]">(Medical Bill Auditor UI)</span></div>
                    <div className="pl-8 text-slate-300">├── main.tsx <span className="text-slate-500 font-sans text-[11px]">(React DOM mount root)</span></div>
                    <div className="pl-8 text-slate-300">└── index.css <span className="text-slate-500 font-sans text-[11px]">(Tailwind v4 theme styling)</span></div>
                    <div className="mt-4 pt-3 border-t border-slate-800 text-slate-400 text-[11px] font-sans">
                      Configured in <code className="text-emerald-400 font-mono">vite.config.ts</code> and <code className="text-emerald-400 font-mono">tsconfig.json</code> for seamless development and production builds.
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Tab 5: JSON Schemas Specification */}
        {activeTab === 'schemas' && (
          <div className="space-y-6">
            <div className="flex items-center justify-between bg-slate-900 p-4 rounded-xl border border-slate-800">
              <div>
                <h3 className="text-sm font-bold text-white">JSON Data Schemas</h3>
                <p className="text-xs text-slate-400 mt-0.5">
                  Confirming <code className="text-rose-400">calculatedPrice</code> and <code className="text-rose-400">userinfo</code> are removed.
                </p>
              </div>

              <div className="flex items-center gap-2">
                <button
                  onClick={() => setSelectedJsonView('final')}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition ${
                    selectedJsonView === 'final'
                      ? 'bg-emerald-500 text-slate-950 font-bold border-emerald-400'
                      : 'bg-slate-800 text-slate-300 border-slate-700 hover:text-white'
                  }`}
                >
                  finalbilljson (Clean)
                </button>
                <button
                  onClick={() => setSelectedJsonView('initial')}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition ${
                    selectedJsonView === 'initial'
                      ? 'bg-emerald-500 text-slate-950 font-bold border-emerald-400'
                      : 'bg-slate-800 text-slate-300 border-slate-700 hover:text-white'
                  }`}
                >
                  userJson (Input)
                </button>
                <button
                  onClick={() => setSelectedJsonView('confirm_prompt')}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition ${
                    selectedJsonView === 'confirm_prompt'
                      ? 'bg-emerald-500 text-slate-950 font-bold border-emerald-400'
                      : 'bg-slate-800 text-slate-300 border-slate-700 hover:text-white'
                  }`}
                >
                  Name-Match Confirm Payload
                </button>
              </div>
            </div>

            {/* Schema Card Details */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              {/* Left Column: Spec Definition */}
              <div className="lg:col-span-1 bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
                <h4 className="text-xs font-bold text-white uppercase tracking-wider">Format Specification</h4>

                {selectedJsonView === 'final' && (
                  <div className="space-y-3 text-xs text-slate-300">
                    <p className="text-emerald-400 font-semibold">FinalBillJson Schema:</p>
                    <div className="bg-slate-850 p-3 rounded-lg border border-slate-800 font-mono text-[11px] leading-relaxed">
                      {`{
  "hospital": str,
  "insurance company": str,
  "initialTotalBill": float,
  "negotiatedFinalTotalBill": float,
  "procedurexName": {
    "code": str | null,
    "initialPrice": float,
    "negotiatedPrice": float
  }
}`}
                    </div>
                    <p className="text-slate-400 text-[11px]">
                      Notice: <code className="text-rose-400">calculatedPrice</code> and <code className="text-rose-400">userinfo</code> have been removed. Procedure code and <code className="text-emerald-400">negotiatedPrice</code> are retained.
                    </p>
                  </div>
                )}

                {selectedJsonView === 'initial' && (
                  <div className="space-y-3 text-xs text-slate-300">
                    <p className="text-cyan-400 font-semibold">UserJson Schema:</p>
                    <div className="bg-slate-850 p-3 rounded-lg border border-slate-800 font-mono text-[11px] leading-relaxed">
                      {`{
  "hospital": str | null,
  "insurance company": str | null,
  "patientProcedures": [
    {
      "name": str | null,
      "code": str | null,
      "statedPrice": float | null
    }
  ]
}`}
                    </div>
                    <p className="text-slate-400 text-[11px]">
                      Extracted from image via <code className="text-cyan-400">backend/Gemini.py</code> or submitted directly via <code className="text-emerald-400">/manual-bill</code>.
                    </p>
                  </div>
                )}

                {selectedJsonView === 'confirm_prompt' && (
                  <div className="space-y-3 text-xs text-slate-300">
                    <p className="text-amber-400 font-semibold">Name-Match Confirmation Response:</p>
                    <div className="bg-slate-850 p-3 rounded-lg border border-slate-800 font-mono text-[11px] leading-relaxed">
                      {`{
  "status": "requires_procedure_confirmation",
  "message": str,
  "confirmations": [
    {
      "procedure_name": str,
      "matched_name": str,
      "matched_code": str,
      "negotiated_price": float,
      "question": "Is [matched_name] what [procedure_name] meant?"
    }
  ]
}`}
                    </div>
                    <p className="text-slate-400 text-[11px]">
                      Returned when the procedure code was not found and the procedure was matched by description, asking the user to confirm.
                    </p>
                  </div>
                )}
              </div>

              {/* Right Column: Live Instance Preview */}
              <div className="lg:col-span-2 bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-sm">
                <div className="bg-slate-850 px-4 py-3 border-b border-slate-800 flex items-center justify-between text-xs">
                  <span className="font-mono text-slate-300 font-medium">
                    Live Output Preview for: {activeHospital}
                  </span>
                  <span className="text-[11px] text-emerald-400 font-mono">application/json</span>
                </div>

                <div className="p-4 bg-slate-950 font-mono text-xs text-emerald-300 overflow-x-auto leading-relaxed max-h-[500px]">
                  <pre>
                    {JSON.stringify(
                      selectedJsonView === 'final'
                        ? finalBillJsonData
                        : selectedJsonView === 'initial'
                        ? userJsonData
                        : confirmPromptPayload,
                      null,
                      2
                    )}
                  </pre>
                </div>
              </div>
            </div>
          </div>
        )}
      </main>

      {/* Footer */}
      <footer className="border-t border-slate-800 bg-slate-900/50 py-4 text-center text-xs text-slate-500">
        BillAudit AI - Medical Bill Error & Savings Scanner (/backend • /frontend • Hospital Folders DB)
      </footer>
    </div>
  );
}
