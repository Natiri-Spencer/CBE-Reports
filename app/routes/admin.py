from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator
from datetime import datetime, timezone
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.auth import admin_only
from app.core.database import get_db
from app.models.admin_activity import AdminActivity
from app.models.fee import Fee
from app.models.marks import Marks
from app.models.user import User
from app.models.learner import Learner
from app.utils.academic_calendar import TERM_SCHEDULE, current_academic_period

router = APIRouter()


class SetupReminder(BaseModel):
    id: str
    title: str
    detail: str


class AcademicStatus(BaseModel):
    students_with_marks: int
    students_without_marks: int
    mark_records: int
    average_score: float | None


class CurrentFeeSummary(BaseModel):
    academic_year: int
    term: int
    learners_with_fee_records: int
    expected: float
    received: float
    outstanding: float


class ActivityRecord(BaseModel):
    id: int
    actor: str
    action: str
    description: str
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def utc_timestamp(cls, value):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class AdminDashboard(BaseModel):
    academic_period: dict[str, str | int]
    counts: dict[str, int]
    setup_reminders: list[SetupReminder]
    academic_status: AcademicStatus
    fee_summary: CurrentFeeSummary
    recent_activity: list[ActivityRecord]


@router.get("/dashboard", response_model=AdminDashboard, operation_id="get_admin_dashboard")
def admin_dashboard(db: Session = Depends(get_db), _admin=Depends(admin_only)):
    academic_year, term = current_academic_period()

    student_count = db.query(func.count(Learner.id)).scalar() or 0
    teacher_count = db.query(func.count(User.id)).filter(User.role == "teacher").scalar() or 0

    current_marks = db.query(Marks).filter(Marks.academic_year == academic_year, Marks.term == term)
    marked_students = current_marks.with_entities(func.count(func.distinct(Marks.learner_id))).scalar() or 0
    marks_count = current_marks.count()
    average_score = current_marks.with_entities(func.avg(Marks.average)).scalar()

    current_fees = db.query(
        func.count(Fee.id),
        func.coalesce(func.sum(Fee.total_required), 0.0),
        func.coalesce(func.sum(Fee.total_paid), 0.0),
        func.coalesce(func.sum(Fee.total_balance), 0.0),
    ).filter(Fee.academic_year == academic_year, Fee.term == term).one()
    fee_count, total_required, total_paid, total_balance = current_fees

    reminders = []
    if teacher_count == 0:
        reminders.append({"id": "teachers", "title": "Add teacher accounts", "detail": "Create teacher sign-ins so staff can enter marks."})
    if student_count == 0:
        reminders.append({"id": "students", "title": "Add learner records", "detail": "Learners appear as marks or fee records are entered."})
    if marks_count == 0:
        reminders.append({"id": "marks", "title": "Enter marks", "detail": "No marks have been recorded yet."})
    if fee_count == 0:
        reminders.append({"id": "fees", "title": "Set up this term's fees", "detail": "No fee records exist for the current term."})
    reminders.append({"id": "academic_setup", "title": "Configure classes and subjects", "detail": "Academic setup is not available yet and is planned for a later screen."})

    activities = db.query(AdminActivity).order_by(AdminActivity.created_at.desc(), AdminActivity.id.desc()).limit(8).all()
    term_info = next(item for item in TERM_SCHEDULE if item["term"] == term)

    return {
        "academic_period": {"academic_year": academic_year, **term_info},
        "counts": {"students": student_count, "teachers": teacher_count},
        "setup_reminders": reminders,
        "academic_status": {
            "students_with_marks": marked_students,
            "students_without_marks": max(student_count - marked_students, 0),
            "mark_records": marks_count,
            "average_score": round(float(average_score), 1) if average_score is not None else None,
        },
        "fee_summary": {
            "academic_year": academic_year,
            "term": term,
            "learners_with_fee_records": fee_count,
            "expected": float(total_required),
            "received": float(total_paid),
            "outstanding": float(total_balance),
        },
        "recent_activity": [
            {
                "id": activity.id,
                "actor": activity.actor_username,
                "action": activity.action,
                "description": activity.description,
                "created_at": activity.created_at.isoformat(),
            }
            for activity in activities
        ],
    }
