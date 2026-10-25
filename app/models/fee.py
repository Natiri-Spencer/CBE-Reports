# app/models/fee.py
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, Date, DateTime, Boolean, ForeignKey, Text
from app.core.database import Base

class Fee(Base):
    __tablename__ = "fees"

    id = Column(Integer, primary_key=True, index=True)
    learner_name = Column(String(255), index=True, nullable=False)
    grade = Column(String(50), index=True, nullable=False)
    academic_year = Column(Integer, index=True, nullable=False, default=0)
    term = Column(Integer, index=True, nullable=False, default=0)

    # Fee categories: required vs paid
    pta_required = Column(Float, default=0.0, nullable=False)
    pta_fee = Column(Float, default=0.0, nullable=False)

    remedials_required = Column(Float, default=0.0, nullable=False)
    remedials_fee = Column(Float, default=0.0, nullable=False)

    welfare_required = Column(Float, default=0.0, nullable=False)
    welfare_fee = Column(Float, default=0.0, nullable=False)

    lunch_required = Column(Float, default=0.0, nullable=False)
    lunch_fee = Column(Float, default=0.0, nullable=False)

    # School fees — flexible, no fixed default
    school_required = Column(Float, nullable=False)
    school_fee = Column(Float, default=0.0, nullable=False)

    # Totals (auto-calculated in backend logic)
    total_required = Column(Float, default=0.0, nullable=False)
    total_paid = Column(Float, default=0.0, nullable=False)
    total_balance = Column(Float, default=0.0, nullable=False)


class FeePayment(Base):
    __tablename__ = "fee_payments"

    id = Column(Integer, primary_key=True, index=True)
    fee_id = Column(Integer, ForeignKey("fees.id", ondelete="CASCADE"), index=True, nullable=False)
    payment_date = Column(Date, nullable=True)
    category = Column(String(32), nullable=False)
    amount = Column(Float, nullable=False)
    reference = Column(String(120), nullable=True)
    note = Column(Text, nullable=True)
    is_opening_balance = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
 
