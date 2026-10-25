from app.core.privacy import stream_pdf
import io
import csv
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List
from fastapi.responses import StreamingResponse, Response
from sqlalchemy.orm import Session
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
from reportlab.lib import colors

from app.core.database import get_db
from app.core.auth import teacher_only, get_current_user
from app.models.marks import Marks
from app.models.learner import Learner
from app.models.api import MarksSubmission, MarkRecord, MarksSaved, Page, Scores
from app.core.idempotency import IdempotencyKey, execute_once
from app.utils.academic_calendar import current_academic_period
from app.services.grading import grade_comment

router = APIRouter()

def serialize_mark(record: Marks):
    return MarkRecord.model_validate(record).model_dump(mode="json")


def mark_query(db, academic_year=None, term=None, class_name=None):
    current_year, current_term = current_academic_period()
    term = current_term if term is None else term
    academic_year = (0 if term == 0 else current_year) if academic_year is None else academic_year
    if not ((academic_year == 0 and term == 0) or (2000 <= academic_year <= 2200 and 1 <= term <= 3)):
        raise HTTPException(status_code=422, detail="Use a valid academic year and term, or year 0 and term 0 for legacy records")
    query = db.query(Marks).filter(Marks.academic_year == academic_year, Marks.term == term)
    if class_name is not None:
        query = query.filter(Marks.class_name == class_name)
    return query


@router.get("", response_model=Page[MarkRecord], operation_id="list_marks")
def list_marks(academic_year: int | None = None, term: int | None = None, class_name: str | None = None,
               limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
               db: Session = Depends(get_db), _user=Depends(get_current_user)):
    query = mark_query(db, academic_year, term, class_name)
    return {"items": query.order_by(Marks.class_name, Marks.rank, Marks.id).offset(offset).limit(limit).all(),
            "total": query.count(), "limit": limit, "offset": offset}

@router.post("/submit", response_model=MarksSaved, operation_id="submit_marks")
def submit_marks(data: MarksSubmission, idempotency_key: IdempotencyKey,
                 db: Session = Depends(get_db), teacher=Depends(teacher_only)):
    def save():
        submitted = []
        periods = set()
        for student in data.students:
            learner = db.get(Learner, str(student.learner_id))
            if learner is None:
                raise HTTPException(status_code=404, detail="Learner not found")
            values = student.model_dump(include=set(Scores.model_fields))
            total = sum(values.values())
            average = round(total / len(values), 2)
            mark_record = db.query(Marks).filter_by(learner_id=learner.id, class_name=student.class_name,
                        academic_year=student.academic_year, term=student.term).one_or_none()
            if mark_record is None:
                mark_record = Marks(learner_id=learner.id, class_name=student.class_name,
                                    academic_year=student.academic_year, term=student.term)
                db.add(mark_record)
            mark_record.name = learner.name
            for field, value in values.items():
                setattr(mark_record, field, value)
            mark_record.total = total
            mark_record.average = average
            mark_record.status = grade_comment(average)
            submitted.append(mark_record)
            periods.add((student.class_name, student.academic_year, student.term))
        db.flush()
        for class_name, year, term in periods:
            ranked = mark_query(db, year, term, class_name).order_by(Marks.total.desc(), Marks.name, Marks.learner_id).all()
            for rank, record in enumerate(ranked, start=1):
                record.rank = rank
        db.flush()
        return {"message": "Marks saved successfully", "results": [serialize_mark(record) for record in submitted]}
    return execute_once(db, teacher.id, "marks:submit", idempotency_key, data.model_dump(mode="json"), save)

# CSV export with ranking
@router.get("/export", operation_id="download_marks_csv", response_class=StreamingResponse,
            responses={200: {"content": {"text/csv": {"schema": {"type": "string"}}}}})
def export_marks(academic_year: int | None = None, term: int | None = None, class_name: str | None = None,
                 db: Session = Depends(get_db), _user=Depends(get_current_user)):
    students = mark_query(db, academic_year, term, class_name).order_by(Marks.class_name, Marks.rank, Marks.id).all()
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        "Rank", "Name", "Learner ID", "Class", "Academic Year", "Term", "Total", "Average", "Status",
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
            student.kiswahili, student.creative_arts
        ]
        total = sum(scores)
        average = round(total / len(scores), 2)
        status = grade_comment(average)
        student_results.append((student, total, average, status))

    # Sort by total descending
    student_results.sort(key=lambda x: x[1], reverse=True)

    # Write rows with rank
    for rank, (student, total, average, status) in enumerate(student_results, start=1):
        writer.writerow([
            student.rank, student.name, student.learner_id, student.class_name, student.academic_year, student.term, total, average, status,
            student.mathematics, grade_comment(student.mathematics),
            student.pretechnical, grade_comment(student.pretechnical),
            student.cre, grade_comment(student.cre),
            student.agriculture, grade_comment(student.agriculture),
            student.integrated_science, grade_comment(student.integrated_science),
            student.social_studies, grade_comment(student.social_studies),
            student.english, grade_comment(student.english),
            student.kiswahili, grade_comment(student.kiswahili),
            student.creative_arts, grade_comment(student.creative_arts),
        ])

    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=marks_export.csv"}
    )

# PDF export with ranking + summary
@router.get("/export/pdf", operation_id="download_marks_pdf", response_class=Response,
            responses={200: {"content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}}}})
def export_marks_pdf(academic_year: int | None = None, term: int | None = None, class_name: str | None = None,
                     db: Session = Depends(get_db), _user=Depends(get_current_user)):
    students = mark_query(db, academic_year, term, class_name).order_by(Marks.class_name, Marks.rank, Marks.id).all()
    filename = "marks_export.pdf"
    buffer = io.BytesIO()

    doc = SimpleDocTemplate(buffer, pagesize=A4)
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
            student.kiswahili, student.creative_arts
        ]
        total = sum(scores)
        average = round(total / len(scores), 2)
        status = grade_comment(average)
        student_results.append((student, total, average, status))
        all_totals.append(total)
        all_averages.append(average)

    # Sort by total descending
    student_results.sort(key=lambda x: x[1], reverse=True)

    # Build rows with rank
    for rank, (student, total, average, status) in enumerate(student_results, start=1):
        row = [
            student.rank, student.name,
            student.mathematics, grade_comment(student.mathematics),
            student.pretechnical, grade_comment(student.pretechnical),
            student.cre, grade_comment(student.cre),
            student.agriculture, grade_comment(student.agriculture),
            student.integrated_science, grade_comment(student.integrated_science),
            student.social_studies, grade_comment(student.social_studies),
            student.english, grade_comment(student.english),
            student.kiswahili, grade_comment(student.kiswahili),
            student.creative_arts, grade_comment(student.creative_arts),
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

    return stream_pdf(buffer, filename)
