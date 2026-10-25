from app.core.privacy import stream_pdf
"""Reports join by permanent identity and academic context, never display name."""
import csv
from io import BytesIO, StringIO
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import and_, func
from sqlalchemy.orm import Session
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

from app.core.auth import admin_only
from app.core.database import get_db
from app.models.api import MarkRecord
from app.models.fee import Fee
from app.models.learner import Learner
from app.models.marks import Marks
from app.routes.fees import FeeRecord
from app.utils.academic_calendar import TERM_SCHEDULE, current_academic_period

router = APIRouter()


class ReportEntry(BaseModel):
    learner_id: UUID
    learner_name: str
    grade: str
    marks: MarkRecord | None
    fees: FeeRecord


class GradeSummary(BaseModel):
    num_learners: int
    total_required: float
    total_paid: float
    total_balance: float
    average_class_score: float | None


class SchoolSummary(BaseModel):
    total_learners: int
    total_required: float
    total_paid: float
    total_balance: float
    average_school_score: float | None


class DashboardReport(BaseModel):
    academic_year: int
    term: int
    term_schedule: dict[str, str | int] | None
    items: list[ReportEntry]
    total: int
    limit: int
    offset: int
    grades: dict[str, list[ReportEntry]]
    grade_summaries: dict[str, GradeSummary]
    school_summary: SchoolSummary


class LearnerReport(BaseModel):
    learner_id: UUID
    learner_name: str
    class_name: str | None
    academic_year: int
    term: int
    marks: MarkRecord | None
    fees: FeeRecord | None


def requested_academic_period(academic_year, term):
    current_year, current_term = current_academic_period()
    term = current_term if term is None else term
    academic_year = (0 if term == 0 else current_year) if academic_year is None else academic_year
    if not ((academic_year == 0 and term == 0) or (2000 <= academic_year <= 2200 and 1 <= term <= 3)):
        raise HTTPException(status_code=422, detail="Use a valid year/term or year 0 and term 0 for legacy records")
    return academic_year, term


def period_fees(db, year, term):
    return db.query(Fee, Marks).outerjoin(Marks, and_(Marks.learner_id == Fee.learner_id,
        Marks.class_name == Fee.grade, Marks.academic_year == Fee.academic_year, Marks.term == Fee.term)).filter(
        Fee.academic_year == year, Fee.term == term)


def report_entry(fee, marks):
    return ReportEntry(learner_id=fee.learner_id, learner_name=fee.learner_name, grade=fee.grade,
        marks=MarkRecord.model_validate(marks) if marks else None, fees=FeeRecord.model_validate(fee))


@router.get("/dashboard", response_model=DashboardReport, operation_id="get_dashboard_report",
            responses={200: {"content": {"text/csv": {"schema": {"type": "string"}}, "application/pdf": {"schema": {"type": "string", "format": "binary"}}}}})
def school_dashboard(academic_year: int | None = None, term: int | None = None,
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), export: str | None = Query(None, pattern="^(csv|pdf)$"),
    db: Session = Depends(get_db), _admin=Depends(admin_only)):
    year, term = requested_academic_period(academic_year, term)
    query = period_fees(db, year, term)
    total = query.count()
    grade_summaries = {}
    for grade, count, required, paid, balance, average in query.with_entities(
        Fee.grade, func.count(Fee.id), func.sum(Fee.total_required), func.sum(Fee.total_paid),
        func.sum(Fee.total_balance), func.avg(Marks.average)).group_by(Fee.grade).all():
        grade_summaries[grade] = GradeSummary(num_learners=count, total_required=required or 0,
            total_paid=paid or 0, total_balance=balance or 0, average_class_score=average)
    summary = SchoolSummary(total_learners=total,
        total_required=sum(s.total_required for s in grade_summaries.values()),
        total_paid=sum(s.total_paid for s in grade_summaries.values()),
        total_balance=sum(s.total_balance for s in grade_summaries.values()),
        average_school_score=query.with_entities(func.avg(Marks.average)).scalar())
    ordered = query.order_by(Fee.grade, Fee.learner_name, Fee.learner_id, Fee.id)
    if export == "csv":
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow(["Learner ID", "Learner Name", "Class", "Academic Year", "Term", "Total Marks", "Average", "Status", "Rank", "Total Required", "Total Paid", "Total Balance"])
        for fee, mark in ordered.yield_per(200):
            writer.writerow([fee.learner_id, fee.learner_name, fee.grade, year, term,
                mark.total if mark else None, mark.average if mark else None, mark.status if mark else None,
                mark.rank if mark else None, fee.total_required, fee.total_paid, fee.total_balance])
        return Response(output.getvalue(), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="dashboard.csv"'})
    if export == "pdf":
        buffer = BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=A4)
        y = A4[1] - 50
        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawString(50, y, f"School Dashboard Report - {year} Term {term}")
        y -= 30
        pdf.setFont("Helvetica", 10)
        for label, value in summary.model_dump().items():
            pdf.drawString(50, y, f"{label.replace('_', ' ').title()}: {value if value is not None else 'Unavailable'}")
            y -= 16
        for grade, values in grade_summaries.items():
            if y < 170:
                pdf.showPage()
                y = A4[1] - 50
            y -= 24
            pdf.setFont("Helvetica-Bold", 12)
            pdf.drawString(50, y, f"Class: {grade}")
            pdf.setFont("Helvetica", 10)
            for label, value in values.model_dump().items():
                y -= 16
                pdf.drawString(60, y, f"{label.replace('_', ' ').title()}: {value if value is not None else 'Unavailable'}")
        pdf.save()
        return stream_pdf(buffer, "dashboard.pdf")
    items = [report_entry(fee, mark) for fee, mark in ordered.offset(offset).limit(limit).all()]
    grades = {}
    for item in items:
        grades.setdefault(item.grade, []).append(item)
    return DashboardReport(academic_year=year, term=term,
        term_schedule=next((row for row in TERM_SCHEDULE if row["term"] == term), None),
        items=items, total=total, limit=limit, offset=offset, grades=grades,
        grade_summaries=grade_summaries, school_summary=summary)


def learner_records(db, learner_id, year, term, class_name):
    learner = db.get(Learner, str(learner_id))
    if learner is None:
        raise HTTPException(status_code=404, detail="Learner not found")
    marks = db.query(Marks).filter_by(learner_id=learner.id, academic_year=year, term=term)
    fees = db.query(Fee).filter_by(learner_id=learner.id, academic_year=year, term=term)
    if class_name:
        marks = marks.filter(Marks.class_name == class_name)
        fees = fees.filter(Fee.grade == class_name)
    if marks.count() > 1 or fees.count() > 1:
        raise HTTPException(status_code=409, detail="Specify class_name to select one academic record")
    mark, fee = marks.first(), fees.first()
    if mark and fee and mark.class_name != fee.grade:
        raise HTTPException(status_code=409, detail="Specify class_name; marks and fees belong to different classes")
    return learner, mark, fee


@router.get("/learner/{learner_id}", response_model=LearnerReport, operation_id="get_learner_report")
def learner_report(learner_id: UUID, academic_year: int | None = None, term: int | None = None, class_name: str | None = None,
                   db: Session = Depends(get_db), _admin=Depends(admin_only)):
    year, term = requested_academic_period(academic_year, term)
    learner, mark, fee = learner_records(db, learner_id, year, term, class_name)
    return LearnerReport(learner_id=learner.id, learner_name=learner.name,
        class_name=mark.class_name if mark else fee.grade if fee else class_name,
        academic_year=year, term=term, marks=MarkRecord.model_validate(mark) if mark else None,
        fees=FeeRecord.model_validate(fee) if fee else None)


@router.get("/learner/{learner_id}/pdf", operation_id="download_learner_report", response_class=Response,
            responses={200: {"content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}}}})
def learner_report_pdf(learner_id: UUID, academic_year: int | None = None, term: int | None = None, class_name: str | None = None,
                       db: Session = Depends(get_db), _admin=Depends(admin_only)):
    year, term = requested_academic_period(academic_year, term)
    learner, mark, fee = learner_records(db, learner_id, year, term, class_name)
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.setTitle(f"Learner report - {learner.name}")
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(50, A4[1] - 55, "Learner Report")
    pdf.setFont("Helvetica", 10)
    lines = [f"Learner: {learner.name}", f"Learner ID: {learner.id}", f"Academic year: {year}    Term: {term}"]
    if mark:
        lines.append(f"Class: {mark.class_name}")
        for field in ("mathematics", "pretechnical", "cre", "agriculture", "integrated_science", "social_studies", "english", "kiswahili", "creative_arts"):
            lines.append(f"{field.replace('_', ' ').title()}: {getattr(mark, field)}")
        lines += [f"Total: {mark.total}    Average: {mark.average}    Rank: {mark.rank}", f"Status: {mark.status}"]
    if fee:
        lines += [f"Fees required: KES {fee.total_required:.2f}", f"Paid: KES {fee.total_paid:.2f}", f"Balance: KES {fee.total_balance:.2f}"]
    y = A4[1] - 83
    for line in lines:
        pdf.drawString(50, y, line)
        y -= 18
    pdf.save()
    return stream_pdf(buffer, "learner-report.pdf")
