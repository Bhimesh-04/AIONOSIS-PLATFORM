from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient
from bson import ObjectId
import datetime

app = Flask(__name__)
CORS(app)  # allow calls from your HTML dashboards[web:32][web:35]

# ---------- MONGODB CONNECTION ----------
client = MongoClient("mongodb://localhost:27017/")
db = client["ainosis"]  # single DB for whole platform[web:37]

patients_col = db["patients"]
doctors_col = db["doctors"]
prescriptions_col = db["prescriptions"]
lab_results_col = db["lab_results"]
cases_col = db["cases"]


# ---------- HELPERS: AADHAAR-BASED UPSERT ----------

def get_or_create_patient(aadhaar, extra=None):
    """Find patient by Aadhaar or create a new one."""
    if extra is None:
        extra = {}
    patient = patients_col.find_one({"aadhaar": aadhaar})
    if not patient:
        patients_col.insert_one({
            "aadhaar": aadhaar,
            "created_at": datetime.datetime.utcnow(),
            **extra
        })
        patient = patients_col.find_one({"aadhaar": aadhaar})
    return patient


def get_or_create_doctor(aadhaar, extra=None):
    """Find doctor by Aadhaar or create a new one."""
    if extra is None:
        extra = {}
    doctor = doctors_col.find_one({"aadhaar": aadhaar})
    if not doctor:
        doctors_col.insert_one({
            "aadhaar": aadhaar,
            "created_at": datetime.datetime.utcnow(),
            **extra
        })
        doctor = doctors_col.find_one({"aadhaar": aadhaar})
    return doctor


def serialize_mongo(doc):
    """Convert ObjectId and datetime to strings for JSON."""
    if not doc:
        return doc
    doc = dict(doc)
    if "_id" in doc:
        doc["_id"] = str(doc["_id"])
    for k, v in list(doc.items()):
        if isinstance(v, datetime.datetime):
            doc[k] = v.isoformat()
    return doc


# ---------- DOCTOR: PRESCRIPTIONS & CASES ----------

@app.route("/api/doctor/prescriptions", methods=["POST"])
def create_prescription():
    """
    Body JSON:
    {
      "patient_aadhaar": "...",
      "doctor_aadhaar": "...",
      "medicines": [
        {"name": "...", "dose": "...", "frequency": "...", "duration": "..."}
      ],
      "notes": "free text",
      "status": "active" | "dispensed" | "cancelled"
    }
    """
    data = request.json or {}
    patient_aadhaar = data.get("patient_aadhaar")
    doctor_aadhaar = data.get("doctor_aadhaar")

    if not patient_aadhaar or not doctor_aadhaar:
        return jsonify({"error": "patient_aadhaar and doctor_aadhaar required"}), 400

    patient = get_or_create_patient(patient_aadhaar)
    doctor = get_or_create_doctor(doctor_aadhaar)

    pres = {
        "patient_aadhaar": patient["aadhaar"],
        "doctor_aadhaar": doctor["aadhaar"],
        "medicines": data.get("medicines", []),
        "notes": data.get("notes", ""),
        "status": data.get("status", "active"),
        "created_at": datetime.datetime.utcnow()
    }
    result = prescriptions_col.insert_one(pres)
    pres["_id"] = str(result.inserted_id)
    return jsonify(pres), 201


@app.route("/api/doctor/cases", methods=["POST"])
def create_case():
    """
    Body JSON:
    {
      "patient_aadhaar": "...",
      "doctor_aadhaar": "...",
      "chief_complaint": "...",
      "diagnosis": "...",
      "plan": "..."
    }
    """
    data = request.json or {}
    patient_aadhaar = data.get("patient_aadhaar")
    doctor_aadhaar = data.get("doctor_aadhaar")

    if not patient_aadhaar or not doctor_aadhaar:
        return jsonify({"error": "patient_aadhaar and doctor_aadhaar required"}), 400

    patient = get_or_create_patient(patient_aadhaar)
    doctor = get_or_create_doctor(doctor_aadhaar)

    case_doc = {
        "patient_aadhaar": patient["aadhaar"],
        "doctor_aadhaar": doctor["aadhaar"],
        "chief_complaint": data.get("chief_complaint", ""),
        "diagnosis": data.get("diagnosis", ""),
        "plan": data.get("plan", ""),
        "created_at": datetime.datetime.utcnow()
    }
    result = cases_col.insert_one(case_doc)
    case_doc["_id"] = str(result.inserted_id)
    return jsonify(case_doc), 201


# ---------- LABORATORY: LAB RESULTS ----------

@app.route("/api/lab/results", methods=["POST"])
def create_lab_result():
    """
    Body JSON:
    {
      "patient_aadhaar": "...",
      "doctor_aadhaar": "...",     # optional
      "test_name": "...",
      "result": "...",
      "unit": "mg/dL",
      "reference_range": "70-110",
      "status": "completed" | "pending"
    }
    """
    data = request.json or {}
    patient_aadhaar = data.get("patient_aadhaar")

    if not patient_aadhaar:
        return jsonify({"error": "patient_aadhaar required"}), 400

    patient = get_or_create_patient(patient_aadhaar)

    lab_doc = {
        "patient_aadhaar": patient["aadhaar"],
        "test_name": data.get("test_name"),
        "result": data.get("result"),
        "unit": data.get("unit"),
        "reference_range": data.get("reference_range"),
        "ordered_by_doctor_aadhaar": data.get("doctor_aadhaar"),
        "status": data.get("status", "completed"),
        "created_at": datetime.datetime.utcnow()
    }
    result = lab_results_col.insert_one(lab_doc)
    lab_doc["_id"] = str(result.inserted_id)
    return jsonify(lab_doc), 201


# ---------- PATIENT VIEW / HISTORY (DOCTOR + USER) ----------

@app.route("/api/patient/<aadhaar>/history", methods=["GET"])
def get_patient_history(aadhaar):
    """
    Returns patient core info + prescriptions + lab_results + cases
    for use in doctor 'Records/Patient history' and user dashboard.
    """
    patient = patients_col.find_one({"aadhaar": aadhaar})
    if not patient:
        return jsonify({"error": "patient not found"}), 404

    prescriptions = [serialize_mongo(d) for d in prescriptions_col.find({"patient_aadhaar": aadhaar})]
    lab_results = [serialize_mongo(d) for d in lab_results_col.find({"patient_aadhaar": aadhaar})]
    cases = [serialize_mongo(d) for d in cases_col.find({"patient_aadhaar": aadhaar})]

    return jsonify({
        "patient": serialize_mongo(patient),
        "prescriptions": prescriptions,
        "lab_results": lab_results,
        "cases": cases
    }), 200


@app.route("/api/patient/<aadhaar>/prescriptions", methods=["GET"])
def get_patient_prescriptions(aadhaar):
    docs = [serialize_mongo(d) for d in prescriptions_col.find({"patient_aadhaar": aadhaar})]
    return jsonify(docs), 200


@app.route("/api/patient/<aadhaar>/lab-results", methods=["GET"])
def get_patient_lab_results(aadhaar):
    docs = [serialize_mongo(d) for d in lab_results_col.find({"patient_aadhaar": aadhaar})]
    return jsonify(docs), 200


# ---------- MEDICAL STORE FLOWS ----------

@app.route("/api/store/prescriptions/<aadhaar>", methods=["GET"])
def store_get_prescriptions_by_patient(aadhaar):
    """
    For medical store dashboard:
    fetch all prescriptions for a patient Aadhaar.
    """
    docs = [serialize_mongo(d) for d in prescriptions_col.find({"patient_aadhaar": aadhaar})]
    return jsonify(docs), 200


@app.route("/api/store/prescription/<prescription_id>", methods=["PATCH"])
def store_update_prescription(prescription_id):
    """
    For medical store dashboard to update status/notes, e.g. mark dispensed.

    Body JSON:
    {
      "status": "dispensed",
      "notes": "Delivered on 2025-12-18"
    }
    """
    data = request.json or {}

    try:
        oid = ObjectId(prescription_id)
    except Exception:
        return jsonify({"error": "invalid prescription_id"}), 400

    update = {}
    if "status" in data:
        update["status"] = data["status"]
    if "notes" in data:
        update["notes"] = data["notes"]

    if not update:
        return jsonify({"error": "nothing to update"}), 400

    res = prescriptions_col.update_one({"_id": oid}, {"$set": update})
    if res.matched_count == 0:
        return jsonify({"error": "prescription not found"}), 404

    doc = prescriptions_col.find_one({"_id": oid})
    return jsonify(serialize_mongo(doc)), 200


@app.route("/api/store/patient/<aadhaar>", methods=["GET"])
def store_get_patient(aadhaar):
    """
    For store dashboard: quick patient details block.
    """
    patient = patients_col.find_one({"aadhaar": aadhaar})
    if not patient:
        return jsonify({"error": "patient not found"}), 404
    return jsonify(serialize_mongo(patient)), 200


@app.route("/api/store/doctor/<aadhaar>", methods=["GET"])
def store_get_doctor(aadhaar):
    """
    For store dashboard: show prescribing doctor details.
    """
    doctor = doctors_col.find_one({"aadhaar": aadhaar})
    if not doctor:
        return jsonify({"error": "doctor not found"}), 404
    return jsonify(serialize_mongo(doctor)), 200


# ---------- ROOT HEALTH CHECK ----------

@app.route("/", methods=["GET"])
def index():
    return jsonify({"status": "ok", "service": "AINOSIS main-app", "time": datetime.datetime.utcnow().isoformat()}), 200


if __name__ == "__main__":
    # For dev only; in production use gunicorn/uwsgi etc.[web:39]
    app.run(host="127.0.0.1", port=5000, debug=True)
