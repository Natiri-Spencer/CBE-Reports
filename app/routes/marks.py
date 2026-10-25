import os
import io
import csv
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from typing import List
from fastapi.responses import StreamingResponse, FileResponse
from sqlalchemy.orm import Session
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
from reportlab.lib import colors

from app.core.database import get_db
from app.core.auth import teacher_only, get_current_user
from app.models.marks import Marks
from app.services.grading import grade_comment

router = APIRouter()

class StudentMarks(BaseModel):
    name: str = Field(..., min_length=1)
    mathematics: float = Field(..., ge=0, le=100)
    pretechnical: float = Field(..., ge=0, le=100)
    cre: float = Field(..., ge=0, le=100)
    agriculture: float = Field(..., ge=0, le=100)
    integrated_science: float = Field(..., ge=0, le=100)
    social_studies: float = Field(..., ge=0, le=100)
    english: float = Field(..., ge=0, le=100)
    kiswahili: float = Field(..., ge=0, le=100)
    creativeArts: float = Field(..., ge=0, le=100)

class MarksSubmission(BaseModel):
    students: List[StudentMarks]


def serialize_mark(record: Marks):
    return {
        "name": record.name,
        "mathematics": record.mathematics,
        "pretechnical": record.pretechnical,
        "cre": record.cre,
        "agriculture": record.agriculture,
        "integratedScience": record.integrated_science,
        "socialStudies": record.social_studies,
        "english": record.english,
        "kiswahili": record.kiswahili,
        "creativeArts": record.creativeArts,
        "total": record.total,
        "average": record.average,
        "status": record.status,
        "rank": record.rank,
    }


@router.get("")
def list_marks(db: Session = Depends(get_db), _user=Depends(get_current_user)):
    records = db.query(Marks).order_by(Marks.total.desc(), Marks.name.asc()).all()
    return [serialize_mark(record) for record in records]

@router.post("/submit")
def submit_marks(data: MarksSubmission, db: Session = Depends(get_db), _teacher=Depends(teacher_only)):
    submitted = []
    try:
        for student in data.students:
            name = student.name.strip()
            if not name:
                continue

            values = student.model_dump(exclude={"name"})
            total = sum(values.values())
            average = round(total / len(values), 2)
            mark_record = next((item for item in submitted if item.name == name), None)
            if mark_record is None:
                matching_records = db.query(Marks).filter(Marks.name == name).order_by(Marks.id.desc()).all()
                mark_record = matching_records[0] if matching_records else None
                for duplicate in matching_records[1:]:
                    db.delete(duplicate)
            if mark_record is None:
                mark_record = Marks(name=name)
                db.add(mark_record)

            for field, value in values.items():
                setattr(mark_record, field, value)
            mark_record.total = total
            mark_record.average = average
            mark_record.status = grade_comment(round(average))
            submitted.append(mark_record)

        db.flush()
        ranked = db.query(Marks).order_by(Marks.total.desc(), Marks.name.asc()).all()
        for rank, record in enumerate(ranked, start=1):
            record.rank = rank
        db.commit()

        return {
            "message": "Marks saved successfully",
            "results": [serialize_mark(record) for record in submitted],
        }
    except Exception:
        db.rollback()
        raise

# CSV export with ranking
@router.get("/export")
def export_marks(db: Session = Depends(get_db), _user=Depends(get_current_user)):
    students = db.query(Marks).all()
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "Rank", "Name", "Total", "Average", "Status",
        "Mathematics", "Mathematics Comment",
        "Pretechnical", "Pretechnical Comment",
        "CRE", "CRE Comment",
        "Agriculture", "Agriculture Comment",
        "Integrated Science", "Integrated Science Comment",
        "Social Studies", "Social Studies Comment",
        "English", "English Comment",
        "Kiswahili", "Kiswahili Comment",
        "Creative Arts", "Creative Arts Comment"
    ])

    # Compute totals/averages first
    student_results = []
    for student in students:
        scores = [
            student.mathematics, student.pretechnical, student.cre,
            student.agriculture, student.integrated_science,
            student.social_studies, student.english,
            student.kiswahili, student.creativeArts
        ]
        total = sum(scores)
        average = total / len(scores)
        status = grade_comment(int(average))
        student_results.append((student, total, average, status))

    # Sort by total descending
    student_results.sort(key=lambda x: x[1], reverse=True)

    # Write rows with rank
    for rank, (student, total, average, status) in enumerate(student_results, start=1):
        writer.writerow([
            rank, student.name, total, average, status,
            student.mathematics, grade_comment(student.mathematics),
            student.pretechnical, grade_comment(student.pretechnical),
            student.cre, grade_comment(student.cre),
            student.agriculture, grade_comment(student.agriculture),
            student.integrated_science, grade_comment(student.integrated_science),
            student.social_studies, grade_comment(student.social_studies),
            student.english, grade_comment(student.english),
            student.kiswahili, grade_comment(student.kiswahili),
            student.creativeArts, grade_comment(student.creativeArts),
        ])

    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=marks_export.csv"}
    )

# PDF export with ranking + summary
@router.get("/export/pdf")
def export_marks_pdf(db: Session = Depends(get_db), _user=Depends(get_current_user)):
    students = db.query(Marks).all()
    filename = "marks_export.pdf"
    filepath = os.path.join("exports", filename)
    os.makedirs("exports", exist_ok=True)

    doc = SimpleDocTemplate(filepath, pagesize=A4)
    elements = []

    # Table header
    data = [["Rank", "Name",
             "Mathematics", "Math Comment",
             "Pretechnical", "Pretechnical Comment",
             "CRE", "CRE Comment",
             "Agriculture", "Agriculture Comment",
             "Integrated Science", "Science Comment",
             "Social Studies", "Social Studies Comment",
             "English", "English Comment",
             "Kiswahili", "Kiswahili Comment",
             "Creative Arts", "Creative Arts Comment",
             "Total", "Average", "Status"]]

    # Compute totals/averages
    student_results = []
    all_totals, all_averages = [], []
    for student in students:
        scores = [
            student.mathematics, student.pretechnical, student.cre,
            student.agriculture, student.integrated_science,
            student.social_studies, student.english,
            student.kiswahili, student.creativeArts
        ]
        total = sum(scores)
        average = total / len(scores)
        status = grade_comment(int(average))
        student_results.append((student, total, average, status))
        all_totals.append(total)
        all_averages.append(average)

    # Sort by total descending
    student_results.sort(key=lambda x: x[1], reverse=True)

    # Build rows with rank
    for rank, (student, total, average, status) in enumerate(student_results, start=1):
        row = [
            rank, student.name,
            student.mathematics, grade_comment(student.mathematics),
            student.pretechnical, grade_comment(student.pretechnical),
            student.cre, grade_comment(student.cre),
            student.agriculture, grade_comment(student.agriculture),
            student.integrated_science, grade_comment(student.integrated_science),
            student.social_studies, grade_comment(student.social_studies),
            student.english, grade_comment(student.english),
            student.kiswahili, grade_comment(student.kiswahili),
            student.creativeArts, grade_comment(student.creativeArts),
            total, f"{average:.2f}", status
        ]
        data.append(row)

    # Add class summary row
    if all_totals and all_averages:
        class_avg = sum(all_averages) / len(all_averages)
        highest = max(all_totals)
        lowest = min(all_totals)
        summary_row = [
            "CLASS SUMMARY", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "",
            f"Highest: {highest}", f"Class Avg: {class_avg:.2f}", f"Lowest: {lowest}"
        ]
        data.append(summary_row)

    # Style table
    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.grey),
        ("TEXTCOLOR", (0,0), (-1,0), colors.whitesmoke),
        ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("BOTTOMPADDING", (0,0), (-1,0), 12),
        ("GRID", (0,0), (-1,-1), 0.5, colors.black),
        ("BACKGROUND", (0,-1), (-1,-1), colors.lightgrey),
        ("FONTNAME", (0,-1), (-1,-1), "Helvetica-Bold"),
    ]))

    elements.append(table)
    doc.build(elements)

    return FileResponse(filepath, media_type="application/pdf", filename=filename)
