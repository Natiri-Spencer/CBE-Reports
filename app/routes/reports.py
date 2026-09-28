from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List
import os, json, pandas as pd
from datetime import datetime

from app.services import report_service
from app.core.auth import admin_only  # role-based access control

router = APIRouter()

LEARNERS_FILE = "learners.json"


def save_learner_name(name: str):
    """Persist learner names in a JSON file."""
    learners = []
    if os.path.exists(LEARNERS_FILE):
        with open(LEARNERS_FILE, "r") as f:
            learners = json.load(f)
    if name not in learners:
        learners.append(name)
        with open(LEARNERS_FILE, "w") as f:
            json.dump(learners, f)


# -------------------------------
# JSON Input Models
# -------------------------------

class StudentEntry(BaseModel):
    learner_name: str
    Grade: int
    ENG: float
    KISW: float
    MAT: float
    INTS: float
    AGN: float
    SST: float
    CRE: float
    CA: float
    PRET: float
    fee_paid: float
    fee_balance: float


class StudentBatch(BaseModel):
    students: List[StudentEntry]


# -------------------------------
# Routes
# -------------------------------

@router.post("/file")
async def generate_reports_from_file(
    performance: UploadFile = File(...),
    fees: UploadFile = File(...)
):
    """
    Teacher: Upload performance + fees CSVs to generate reports.
    """
    try:
        result = report_service.generate_reports(performance.file, fees.file)
        for student in result["students"]:
            save_learner_name(student["Learner Name"])
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/json")
async def generate_reports_from_json(batch: StudentBatch):
    """
    Teacher: Accept JSON input of student marks, grade, and fees.
    Generates per-student records, per-grade summaries, and a PDF booklet.
    """
    try:
        df = pd.DataFrame([s.dict() for s in batch.students])
        df, grade_summary, subject_cols = report_service.compute_reports(df)

        for name in df["learner_name"].unique():
            save_learner_name(name)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        pdf_file = f"Student_Report_Booklet_{timestamp}.pdf"
        report_service.generate_pdf_booklet(df, subject_cols, output_file=pdf_file)

        summary = {
            "students": df.to_dict(orient="records"),
            "grade_summary": grade_summary.to_dict(orient="records"),
            "summary": {
                "total_students": len(df),
                "at_risk": int((df["Status"] == "At Risk").sum()),
                "avg_score": round(float(df["TOTAL"].mean()), 2),
                "total_fees": round(float(df["fee_paid"].sum()), 2),
                "total_balance": round(float(df["fee_balance"].sum()), 2),
                "pdf_path": pdf_file,
            },
        }
        return summary
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/fees", dependencies=[Depends(admin_only)])
async def upload_fees_csv(fees: UploadFile = File(...)):
    """
    Admin: Upload fees CSV only. Protected by role-based access.
    """
    try:
        result = report_service.process_fees(fees.file)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pdf/{filename}")
async def download_pdf(filename: str):
    file_path = os.path.join(os.getcwd(), filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="PDF not found")
    return FileResponse(path=file_path, filename=filename, media_type="application/pdf")
