from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Literal
from io import BytesIO
from datetime import date
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlalchemy import func

from app.core.database import get_db
from app.core.auth import admin_only
from app.models.fee import Fee, FeePayment
from app.models.admin_activity import AdminActivity
from app.utils.academic_calendar import TERM_SCHEDULE, current_academic_period, validate_term

router = APIRouter()


def require_term(term: int) -> int:
    try:
        return validate_term(term)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def require_period(academic_year: int, term: int):
    require_term(term)
    if term == 0 and academic_year != 0:
        raise HTTPException(status_code=422, detail="Legacy term 0 must use academic_year 0")
    if term != 0 and academic_year < 2000:
        raise HTTPException(status_code=422, detail="Academic year must be 2000 or later")


def filter_period(query, academic_year: Optional[int], term: Optional[int]):
    if academic_year is not None:
        query = query.filter(Fee.academic_year == academic_year)
    if term is not None:
        require_term(term)
        query = query.filter(Fee.term == term)
    return query

class FeeCreate(BaseModel):
    learner_name: str = Field(..., min_length=1)
    grade: str = Field(..., min_length=1)
    academic_year: int = Field(default_factory=lambda: current_academic_period()[0], ge=0, le=2200)
    term: int = Field(default_factory=lambda: current_academic_period()[1], ge=0, le=3)
    pta_required: float = Field(0.0, ge=0)
    remedials_required: float = Field(0.0, ge=0)
    welfare_required: float = Field(0.0, ge=0)
    lunch_required: float = Field(0.0, ge=0)
    school_required: float = Field(0.0, ge=0)

    class Config:
        from_attributes = True


class FeeRecord(FeeCreate):
    id: int
    pta_fee: float
    remedials_fee: float
    welfare_fee: float
    lunch_fee: float
    school_fee: float
    total_required: float
    total_paid: float
    total_balance: float


class PaymentCreate(BaseModel):
    category: Literal["pta", "remedials", "welfare", "lunch", "school"]
    amount: float = Field(..., gt=0)
    payment_date: date
    reference: Optional[str] = Field(None, max_length=120)
    note: Optional[str] = None


class PaymentRecord(BaseModel):
    id: int
    fee_id: int
    category: str
    amount: float
    payment_date: Optional[date]
    reference: Optional[str]
    note: Optional[str]
    is_opening_balance: bool

    class Config:
        from_attributes = True


# -------------------------------
# Helper: totals calculation
# -------------------------------
def calculate_totals(fee: Fee):
    fee.total_required = (
        fee.pta_required +
        fee.remedials_required +
        fee.welfare_required +
        fee.lunch_required +
        fee.school_required
    )
    fee.total_paid = (
        fee.pta_fee +
        fee.remedials_fee +
        fee.welfare_fee +
        fee.lunch_fee +
        fee.school_fee
    )
    fee.total_balance = fee.total_required - fee.total_paid


# -------------------------------
# CRUD Endpoints
# -------------------------------
@router.post("", response_model=FeeRecord)
def create_fee(record: FeeCreate, db: Session = Depends(get_db), _admin=Depends(admin_only)):
    require_period(record.academic_year, record.term)
    values = record.dict()
    values["learner_name"] = record.learner_name.strip()
    values["grade"] = record.grade.strip()
    new_fee = db.query(Fee).filter(
        Fee.learner_name == values["learner_name"],
        Fee.grade == values["grade"],
        Fee.academic_year == record.academic_year,
        Fee.term == record.term,
    ).first()
    created = new_fee is None
    if created:
        new_fee = Fee(
            **values,
            pta_fee=0,
            remedials_fee=0,
            welfare_fee=0,
            lunch_fee=0,
            school_fee=0,
        )
        db.add(new_fee)
    else:
        for field, value in values.items():
            setattr(new_fee, field, value)
    calculate_totals(new_fee)
    db.flush()
    db.add(AdminActivity(
        actor_username=_admin.username,
        action="fee_record_created" if created else "fee_record_updated",
        entity_type="fee_record",
        entity_id=str(new_fee.id),
        description="Created a fee record" if created else "Updated a fee record",
    ))
    db.commit()
    db.refresh(new_fee)
    return new_fee


@router.get("", response_model=List[FeeRecord])
def list_fees(
    academic_year: Optional[int] = None,
    term: Optional[int] = None,
    db: Session = Depends(get_db),
    _admin=Depends(admin_only),
):
    query = filter_period(db.query(Fee), academic_year, term)
    return query.order_by(Fee.academic_year.desc(), Fee.term, Fee.grade, Fee.learner_name).all()


@router.get("/calendar")
def academic_calendar(_admin=Depends(admin_only)):
    year, term = current_academic_period()
    return {"academic_year": year, "current_term": term, "terms": TERM_SCHEDULE}


@router.put("/{learner_name}/{grade}", response_model=FeeRecord)
def update_fee(learner_name: str, grade: str, record: FeeCreate, db: Session = Depends(get_db), _admin=Depends(admin_only)):
    require_period(record.academic_year, record.term)
    fee = db.query(Fee).filter(
        Fee.learner_name == learner_name,
        Fee.grade == grade,
        Fee.academic_year == record.academic_year,
        Fee.term == record.term,
    ).first()
    if not fee:
        raise HTTPException(status_code=404, detail="Learner not found")

    for field, value in record.dict(exclude={"learner_name", "grade"}).items():
        setattr(fee, field, value)

    calculate_totals(fee)
    db.add(AdminActivity(
        actor_username=_admin.username,
        action="fee_record_updated",
        entity_type="fee_record",
        entity_id=str(fee.id),
        description="Updated a fee record",
    ))
    db.commit()
    db.refresh(fee)
    return fee


@router.delete("/{learner_name}/{grade}")
def delete_fee(
    learner_name: str,
    grade: str,
    academic_year: Optional[int] = None,
    term: Optional[int] = None,
    db: Session = Depends(get_db),
    _admin=Depends(admin_only),
):
    query = db.query(Fee).filter(Fee.learner_name == learner_name, Fee.grade == grade)
    if academic_year is not None:
        query = query.filter(Fee.academic_year == academic_year)
    if term is not None:
        require_term(term)
        query = query.filter(Fee.term == term)
    matches = query.all()
    if not matches:
        raise HTTPException(status_code=404, detail="Learner not found")
    if len(matches) > 1:
        raise HTTPException(status_code=400, detail="Specify academic_year and term to delete one fee record")
    db.add(AdminActivity(
        actor_username=_admin.username,
        action="fee_record_deleted",
        entity_type="fee_record",
        entity_id=str(matches[0].id),
        description="Deleted a fee record",
    ))
    db.query(FeePayment).filter(FeePayment.fee_id == matches[0].id).delete(synchronize_session=False)
    db.delete(matches[0])
    db.commit()
    return {"message": "Learner deleted"}


# -------------------------------
# Filters
# -------------------------------
@router.get("/grade/{grade}", response_model=List[FeeRecord])
def list_fees_by_grade(
    grade: str,
    academic_year: Optional[int] = None,
    term: Optional[int] = None,
    db: Session = Depends(get_db),
    _admin=Depends(admin_only),
):
    return filter_period(db.query(Fee).filter(Fee.grade == grade), academic_year, term).all()


@router.get("/category/{category}", response_model=List[FeeRecord])
def list_fees_by_category(
    category: str,
    academic_year: Optional[int] = None,
    term: Optional[int] = None,
    db: Session = Depends(get_db),
    _admin=Depends(admin_only),
):
    learners = filter_period(db.query(Fee), academic_year, term).all()
    if not learners:
        raise HTTPException(status_code=404, detail="No learners found")

    category = category.lower()
    if category == "pta":
        return [l for l in learners if l.pta_required > 0 or l.pta_fee > 0]
    elif category == "remedials":
        return [l for l in learners if l.remedials_required > 0 or l.remedials_fee > 0]
    elif category == "welfare":
        return [l for l in learners if l.welfare_required > 0 or l.welfare_fee > 0]
    elif category == "lunch":
        return [l for l in learners if l.lunch_required > 0 or l.lunch_fee > 0]
    elif category == "school":
        return [l for l in learners if l.school_required > 0 or l.school_fee > 0]
    else:
        raise HTTPException(status_code=400, detail="Invalid category")


# -------------------------------
# Summaries
# -------------------------------
@router.get("/summary/all")
def fee_summary_all(
    academic_year: Optional[int] = None,
    term: Optional[int] = None,
    db: Session = Depends(get_db),
    _admin=Depends(admin_only),
) -> Dict[str, float]:
    learners = filter_period(db.query(Fee), academic_year, term).all()

    return {
        "total_learners": len(learners),
        "total_required": sum(l.total_required for l in learners),
        "total_paid": sum(l.total_paid for l in learners),
        "total_balance": sum(l.total_balance for l in learners),
    }


@router.get("/summary/grade/{grade}")
def fee_summary_by_grade(
    grade: str,
    academic_year: Optional[int] = None,
    term: Optional[int] = None,
    db: Session = Depends(get_db),
    _admin=Depends(admin_only),
) -> Dict[str, float | str]:
    learners = filter_period(db.query(Fee).filter(Fee.grade == grade), academic_year, term).all()

    return {
        "grade": grade,
        "total_required": sum(l.total_required for l in learners),
        "collected": sum(l.total_paid for l in learners),
        "balance": sum(l.total_balance for l in learners),
        "num_learners": len(learners),
    }


@router.get("/summary/category/{category}")
def fee_summary_by_category(
    category: str,
    academic_year: Optional[int] = None,
    term: Optional[int] = None,
    db: Session = Depends(get_db),
    _admin=Depends(admin_only),
) -> Dict[str, float | str]:
    learners = filter_period(db.query(Fee), academic_year, term).all()
    category = category.lower()
    if category == "pta":
        filtered = [l for l in learners if l.pta_required > 0 or l.pta_fee > 0]
    elif category == "remedials":
        filtered = [l for l in learners if l.remedials_required > 0 or l.remedials_fee > 0]
    elif category == "welfare":
        filtered = [l for l in learners if l.welfare_required > 0 or l.welfare_fee > 0]
    elif category == "lunch":
        filtered = [l for l in learners if l.lunch_required > 0 or l.lunch_fee > 0]
    elif category == "school":
        filtered = [l for l in learners if l.school_required > 0 or l.school_fee > 0]
    else:
        raise HTTPException(status_code=400, detail="Invalid category")

    return {
        "category": category,
        "total_required": sum(getattr(l, f"{category}_required") for l in filtered),
        "collected": sum(getattr(l, f"{category}_fee") for l in filtered),
        "balance": sum(getattr(l, f"{category}_required") - getattr(l, f"{category}_fee") for l in filtered),
        "num_learners": len(filtered),
    }


@router.get("/records/{fee_id}/payments", response_model=List[PaymentRecord])
def list_payments(fee_id: int, db: Session = Depends(get_db), _admin=Depends(admin_only)):
    fee = db.query(Fee).filter(Fee.id == fee_id).first()
    if fee is None:
        raise HTTPException(status_code=404, detail="Fee record not found")
    return db.query(FeePayment).filter(FeePayment.fee_id == fee_id).order_by(
        FeePayment.payment_date.is_(None), FeePayment.payment_date, FeePayment.id
    ).all()


@router.post("/records/{fee_id}/payments", response_model=PaymentRecord)
def record_payment(
    fee_id: int,
    record: PaymentCreate,
    db: Session = Depends(get_db),
    _admin=Depends(admin_only),
):
    fee = db.query(Fee).filter(Fee.id == fee_id).first()
    if fee is None:
        raise HTTPException(status_code=404, detail="Fee record not found")

    payment = FeePayment(
        fee_id=fee.id,
        category=record.category,
        amount=record.amount,
        payment_date=record.payment_date,
        reference=record.reference,
        note=record.note,
        is_opening_balance=False,
    )
    db.add(payment)
    db.flush()

    paid = db.query(func.coalesce(func.sum(FeePayment.amount), 0.0)).filter(
        FeePayment.fee_id == fee.id,
        FeePayment.category == record.category,
    ).scalar()
    setattr(fee, f"{record.category}_fee", float(paid or 0.0))
    calculate_totals(fee)
    db.add(AdminActivity(
        actor_username=_admin.username,
        action="payment_recorded",
        entity_type="fee_payment",
        entity_id=str(payment.id),
        description="Recorded a fee payment",
    ))
    db.commit()
    db.refresh(payment)
    return payment


def render_fee_statement(fee: Fee, payments: List[FeePayment]) -> Response:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    _, height = A4
    term_info = next((item for item in TERM_SCHEDULE if item["term"] == fee.term), None)
    pdf.setTitle(f"Fee statement - {fee.learner_name} - {fee.academic_year} term {fee.term}")

    def draw_header():
        pdf.setFont("Helvetica-Bold", 16)
        pdf.drawString(45, height - 48, "Student Fee Statement")
        pdf.setFont("Helvetica", 10)
        pdf.drawString(45, height - 70, f"Learner: {fee.learner_name}    Grade: {fee.grade}")
        period = "Legacy / unassigned term" if fee.term == 0 else f"Academic year {fee.academic_year} - Term {fee.term}"
        pdf.drawString(45, height - 87, period)
        if term_info:
            pdf.drawString(45, height - 104, f"{term_info['months']} · {term_info['instruction_weeks']} school weeks")
        pdf.drawString(45, height - 121, f"Statement date: {date.today().isoformat()}")

    draw_header()
    y = height - 153
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(45, y, "Category")
    pdf.drawString(255, y, "Required (KES)")
    pdf.drawString(365, y, "Paid (KES)")
    pdf.drawString(465, y, "Balance")
    y -= 17
    pdf.setFont("Helvetica", 9)
    categories = [
        ("PTA", fee.pta_required, fee.pta_fee),
        ("Remedials", fee.remedials_required, fee.remedials_fee),
        ("Welfare", fee.welfare_required, fee.welfare_fee),
        ("Lunch", fee.lunch_required, fee.lunch_fee),
        ("School", fee.school_required, fee.school_fee),
    ]
    for label, required, paid in categories:
        pdf.drawString(45, y, label)
        pdf.drawRightString(335, y, f"{required:.2f}")
        pdf.drawRightString(435, y, f"{paid:.2f}")
        pdf.drawRightString(545, y, f"{required - paid:.2f}")
        y -= 16

    y -= 8
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(45, y, f"Total required: KES {fee.total_required:.2f}")
    pdf.drawString(245, y, f"Total paid: KES {fee.total_paid:.2f}")
    pdf.drawString(425, y, f"Balance: KES {fee.total_balance:.2f}")
    y -= 30
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(45, y, "Payment history")
    y -= 20
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(45, y, "Date")
    pdf.drawString(150, y, "Category")
    pdf.drawRightString(280, y, "Amount (KES)")
    pdf.drawString(300, y, "Reference / note")
    y -= 16
    pdf.setFont("Helvetica", 8)
    if not payments:
        pdf.drawString(45, y, "No payment records for this term.")
    for payment in payments:
        if y < 55:
            pdf.showPage()
            draw_header()
            y = height - 145
            pdf.setFont("Helvetica-Bold", 9)
            pdf.drawString(45, y, "Date")
            pdf.drawString(150, y, "Category")
            pdf.drawRightString(280, y, "Amount (KES)")
            pdf.drawString(300, y, "Reference / note")
            y -= 16
            pdf.setFont("Helvetica", 8)
        payment_date = payment.payment_date.isoformat() if payment.payment_date else "Date unavailable"
        description = payment.note or payment.reference or ("Opening balance" if payment.is_opening_balance else "")
        pdf.drawString(45, y, payment_date)
        pdf.drawString(150, y, payment.category.title())
        pdf.drawRightString(280, y, f"{payment.amount:.2f}")
        pdf.drawString(300, y, str(description)[:42])
        y -= 14

    pdf.save()
    buffer.seek(0)
    return Response(
        content=buffer.getvalue(),
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="fee_statement.pdf"'},
    )


@router.get("/records/{fee_id}/statement.pdf")
def fee_statement_by_id(fee_id: int, db: Session = Depends(get_db), _admin=Depends(admin_only)):
    fee = db.query(Fee).filter(Fee.id == fee_id).first()
    if fee is None:
        raise HTTPException(status_code=404, detail="Fee record not found")
    payments = db.query(FeePayment).filter(FeePayment.fee_id == fee.id).order_by(
        FeePayment.payment_date.is_(None), FeePayment.payment_date, FeePayment.id
    ).all()
    return render_fee_statement(fee, payments)


@router.get("/{learner_name}/{grade}/statement.pdf")
def fee_statement(learner_name: str, grade: str, db: Session = Depends(get_db), _admin=Depends(admin_only)):
    fee = db.query(Fee).filter(Fee.learner_name == learner_name, Fee.grade == grade).order_by(
        Fee.academic_year.desc(), Fee.term.desc()
    ).first()
    if fee is None:
        raise HTTPException(status_code=404, detail="Fee record not found")
    payments = db.query(FeePayment).filter(FeePayment.fee_id == fee.id).order_by(
        FeePayment.payment_date.is_(None), FeePayment.payment_date, FeePayment.id
    ).all()
    return render_fee_statement(fee, payments)
