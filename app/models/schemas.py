# app/models/schemas.py

from pydantic import BaseModel, EmailStr
from typing import Dict, List, Any


class ReportSummary(BaseModel):
    total_students: int
    at_risk: int
    avg_score: float
    total_fees: float
    total_balance: float
    subject_averages: Dict[str, float]



class FeeBase(BaseModel):
    learner_name: str
    grade: str
    pta_required: float
    pta_fee: float
    remedials_required: float
    remedials_fee: float
    welfare_required: float
    welfare_fee: float
    lunch_required: float
    lunch_fee: float
    school_required: float
    school_fee: float


class FeeCreate(FeeBase):
    pass


class FeeUpdate(FeeBase):
    pass


class Fee(FeeBase):
    total_paid: float
    total_balance: float

    class Config:
        from_attributes = True  # Pydantic v2


class FeeSummary(BaseModel):
    total_fees: float
    total_balance: float
    students: List[Dict[str, Any]]


# -------------------------------
# ✅ Auth Schemas
# -------------------------------

class UserBase(BaseModel):
    username: str
    email: EmailStr


class UserCreate(UserBase):
    password: str


class UserLogin(BaseModel):
    username: str
    password: str


class User(UserBase):
    id: int

    class Config:
        from_attributes = True
