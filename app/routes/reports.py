# app/routes/reports.py
from fastapi import APIRouter, Depends, HTTPException, Response, Query
from sqlalchemy.orm import Session
from typing import Dict, List, Optional
import csv
import io
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
import logging, traceback

from app.core.database import get_db
from app.core.auth import admin_only
from app.utils.academic_calendar import TERM_SCHEDULE, current_academic_period

router = APIRouter()
logger = logging.getLogger("reports_handler")
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("[REPORTS HANDLER] %(asctime)s %(levelname)s: %(message)s"))
    logger.addHandler(h)


def requested_academic_period(academic_year: Optional[int], term: Optional[int]):
    current_year, current_term = current_academic_period()
    selected_term = term if term is not None else current_term
    selected_year = academic_year if academic_year is not None else (0 if selected_term == 0 else current_year)
    if (selected_term == 0) != (selected_year == 0):
        raise HTTPException(status_code=422, detail="Legacy records require academic_year=0 and term=0")
    return selected_year, selected_term

@router.get("/dashboard")
def school_dashboard(
    db: Session = Depends(get_db),
    export: Optional[str] = Query(None),
    academic_year: Optional[int] = Query(None, ge=0, le=2200),
    term: Optional[int] = Query(None, ge=0, le=3),
    _admin=Depends(admin_only),
):
    try:
        # Lazy model imports only
        from app.models.marks import Marks
        from app.models.fee import Fee

        selected_year, selected_term = requested_academic_period(academic_year, term)
        fees = db.query(Fee).filter(
            Fee.academic_year == selected_year,
            Fee.term == selected_term,
        ).all()

        grade_reports: Dict[str, List[Dict]] = {}
        grade_summaries: Dict[str, Dict] = {}
        grade_mark_totals: Dict[str, float] = {}
        grade_mark_counts: Dict[str, int] = {}
        total_marks, num_with_marks = 0.0, 0

        for fee in fees:
            marks = db.query(Marks).filter(Marks.name == fee.learner_name).first()
            learner_report = {
                "learner_name": fee.learner_name,
                "grade": fee.grade,
                "marks": {
                    "mathematics": getattr(marks, "mathematics", None) if marks else None,
                    "english": getattr(marks, "english", None) if marks else None,
                    "kiswahili": getattr(marks, "kiswahili", None) if marks else None,
                    "total": getattr(marks, "total", None) if marks else None,
                    "average": getattr(marks, "average", None) if marks else None,
                    "status": getattr(marks, "status", None) if marks else None,
                    "rank": getattr(marks, "rank", None) if marks else None,
                } if marks else {},
                "fees": {
                    "pta_required": fee.pta_required,
                    "pta_fee": fee.pta_fee,
                    "school_required": fee.school_required,
                    "school_fee": fee.school_fee,
                    "total_required": fee.total_required,
                    "total_paid": fee.total_paid,
                    "total_balance": fee.total_balance,
                }
            }
            grade_reports.setdefault(fee.grade, []).append(learner_report)

            summary = grade_summaries.setdefault(fee.grade, {
                "num_learners": 0,
                "total_required": 0.0,
                "total_paid": 0.0,
                "total_balance": 0.0,
                "average_class_score": 0.0
            })
            summary["num_learners"] += 1
            summary["total_required"] += float(fee.total_required or 0.0)
            summary["total_paid"] += float(fee.total_paid or 0.0)
            summary["total_balance"] += float(fee.total_balance or 0.0)

            if marks and getattr(marks, "average", None) is not None:
                avg = float(marks.average)
                total_marks += avg
                num_with_marks += 1
                grade_mark_totals[fee.grade] = grade_mark_totals.get(fee.grade, 0.0) + avg
                grade_mark_counts[fee.grade] = grade_mark_counts.get(fee.grade, 0) + 1

        for grade, summary in grade_summaries.items():
            marked_count = grade_mark_counts.get(grade, 0)
            summary["average_class_score"] = (
                grade_mark_totals[grade] / marked_count if marked_count else None
            )

        school_summary = {
            "total_learners": len(fees),
            "total_required": sum(s["total_required"] for s in grade_summaries.values()),
            "total_paid": sum(s["total_paid"] for s in grade_summaries.values()),
            "total_balance": sum(s["total_balance"] for s in grade_summaries.values()),
            "average_school_score": (total_marks / num_with_marks) if num_with_marks > 0 else None
        }

        # CSV export
        if export and export.lower() == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow([
                "Learner Name", "Grade", "Mathematics", "English", "Kiswahili",
                "Academic Year", "Term",
                "Total Marks", "Average", "Status", "Rank",
                "PTA Required", "PTA Fee", "School Required", "School Fee",
                "Total Required", "Total Paid", "Total Balance"
            ])
            for grade, learners in grade_reports.items():
                for learner in learners:
                    marks = learner.get("marks", {})
                    fees = learner.get("fees", {})
                    writer.writerow([
                        learner.get("learner_name"),
                        learner.get("grade"),
                        marks.get("mathematics"),
                        marks.get("english"),
                        marks.get("kiswahili"),
                        selected_year,
                        selected_term,
                        marks.get("total"),
                        marks.get("average"),
                        marks.get("status"),
                        marks.get("rank"),
                        fees.get("pta_required"),
                        fees.get("pta_fee"),
                        fees.get("school_required"),
                        fees.get("school_fee"),
                        fees.get("total_required"),
                        fees.get("total_paid"),
                        fees.get("total_balance"),
                    ])
            return Response(content=output.getvalue(), media_type="text/csv")

        # PDF export
        if export and export.lower() == "pdf":
            buffer = io.BytesIO()
            c = canvas.Canvas(buffer, pagesize=A4)
            width, height = A4
            c.setFont("Helvetica-Bold", 14)
            c.drawString(50, height - 50, f"School Dashboard Report - {selected_year} Term {selected_term}")
            y = height - 80
            c.setFont("Helvetica", 10)
            c.drawString(50, y, f"Total Learners: {school_summary['total_learners']}")
            y -= 15
            c.drawString(50, y, f"Total Required: {school_summary['total_required']}")
            y -= 15
            c.drawString(50, y, f"Total Paid: {school_summary['total_paid']}")
            y -= 15
            c.drawString(50, y, f"Total Balance: {school_summary['total_balance']}")
            y -= 15
            c.drawString(50, y, f"Average School Score: {school_summary['average_school_score']}")
            y -= 30
            for grade, summary in grade_summaries.items():
                c.setFont("Helvetica-Bold", 12)
                c.drawString(50, y, f"Grade: {grade}")
                y -= 15
                c.setFont("Helvetica", 10)
                c.drawString(60, y, f"Learners: {summary['num_learners']}")
                y -= 15
                c.drawString(60, y, f"Required: {summary['total_required']}")
                y -= 15
                c.drawString(60, y, f"Paid: {summary['total_paid']}")
                y -= 15
                c.drawString(60, y, f"Balance: {summary['total_balance']}")
                y -= 15
                c.drawString(60, y, f"Average Score: {summary['average_class_score']}")
                y -= 30
                if y < 100:
                    c.showPage()
                    y = height - 50
            c.showPage()
            c.save()
            buffer.seek(0)
            return Response(content=buffer.getvalue(), media_type="application/pdf")

        return {
            "academic_year": selected_year,
            "term": selected_term,
            "term_schedule": next((item for item in TERM_SCHEDULE if item["term"] == selected_term), None),
            "grades": grade_reports,
            "grade_summaries": grade_summaries,
            "school_summary": school_summary
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Unhandled error in /reports/dashboard: %s", exc)
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/learner/{learner_name}")
def learner_report(
    learner_name: str,
    academic_year: Optional[int] = Query(None, ge=0, le=2200),
    term: Optional[int] = Query(None, ge=0, le=3),
    db: Session = Depends(get_db),
    _admin=Depends(admin_only),
):
    from app.models.marks import Marks
    from app.models.fee import Fee

    marks = db.query(Marks).filter(Marks.name == learner_name).first()
    selected_year, selected_term = requested_academic_period(academic_year, term)
    fee = db.query(Fee).filter(
        Fee.learner_name == learner_name,
        Fee.academic_year == selected_year,
        Fee.term == selected_term,
    ).first()
    if marks is None and fee is None:
        raise HTTPException(status_code=404, detail="Learner report not found")

    return {
        "learner_name": learner_name,
        "grade": fee.grade if fee else None,
        "academic_year": fee.academic_year if fee else None,
        "term": fee.term if fee else None,
        "marks": ({
            "mathematics": marks.mathematics,
            "pretechnical": marks.pretechnical,
            "cre": marks.cre,
            "agriculture": marks.agriculture,
            "integrated_science": marks.integrated_science,
            "social_studies": marks.social_studies,
            "english": marks.english,
            "kiswahili": marks.kiswahili,
            "creativeArts": marks.creativeArts,
            "total": marks.total,
            "average": marks.average,
            "status": marks.status,
            "rank": marks.rank,
        } if marks else None),
        "fees": ({
            "pta_required": fee.pta_required,
            "pta_paid": fee.pta_fee,
            "remedials_required": fee.remedials_required,
            "remedials_paid": fee.remedials_fee,
            "welfare_required": fee.welfare_required,
            "welfare_paid": fee.welfare_fee,
            "lunch_required": fee.lunch_required,
            "lunch_paid": fee.lunch_fee,
            "school_required": fee.school_required,
            "school_paid": fee.school_fee,
            "total_required": fee.total_required,
            "total_paid": fee.total_paid,
            "total_balance": fee.total_balance,
        } if fee else None),
    }


@router.get("/learner/{learner_name}/pdf")
def learner_report_pdf(
    learner_name: str,
    academic_year: Optional[int] = Query(None, ge=0, le=2200),
    term: Optional[int] = Query(None, ge=0, le=3),
    db: Session = Depends(get_db),
    _admin=Depends(admin_only),
):
    from app.models.marks import Marks
    from app.models.fee import Fee

    marks = db.query(Marks).filter(Marks.name == learner_name).first()
    selected_year, selected_term = requested_academic_period(academic_year, term)
    fee = db.query(Fee).filter(
        Fee.learner_name == learner_name,
        Fee.academic_year == selected_year,
        Fee.term == selected_term,
    ).first()
    if marks is None and fee is None:
        raise HTTPException(status_code=404, detail="Learner report not found")

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    _, height = A4
    y = height - 55
    pdf.setTitle(f"Learner report - {learner_name}")
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(50, y, "Learner Report")
    y -= 28
    pdf.setFont("Helvetica", 11)
    pdf.drawString(50, y, f"Learner: {learner_name}")
    y -= 18
    if fee:
        pdf.drawString(50, y, f"Grade: {fee.grade}    Academic year: {fee.academic_year}    Term: {fee.term or 'Legacy'}")
        y -= 26

    if marks:
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(50, y, "Marks")
        y -= 20
        pdf.setFont("Helvetica", 10)
        for label, value in [
            ("Mathematics", marks.mathematics), ("English", marks.english),
            ("Kiswahili", marks.kiswahili), ("Creative Arts", marks.creativeArts),
            ("Integrated Science", marks.integrated_science), ("Pretechnical", marks.pretechnical),
            ("Agriculture", marks.agriculture), ("Social Studies", marks.social_studies),
            ("CRE", marks.cre),
        ]:
            pdf.drawString(60, y, f"{label}: {value}")
            y -= 16
        pdf.drawString(60, y, f"Total: {marks.total}    Average: {marks.average}    Rank: {marks.rank}")
        y -= 16
        pdf.drawString(60, y, f"Status: {marks.status or 'Not graded'}")
        y -= 28

    if fee:
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(50, y, "Fees")
        y -= 20
        pdf.setFont("Helvetica", 10)
        pdf.drawString(60, y, f"Required: KES {fee.total_required:.2f}")
        y -= 16
        pdf.drawString(60, y, f"Paid: KES {fee.total_paid:.2f}")
        y -= 16
        pdf.drawString(60, y, f"Balance: KES {fee.total_balance:.2f}")

    pdf.save()
    buffer.seek(0)
    return Response(
        content=buffer.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="learner_report.pdf"'},
    )
