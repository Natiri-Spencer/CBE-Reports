# app/models/schemas.py

from pydantic import BaseModel
from typing import Dict, List


class ReportSummary(BaseModel):
    """
    Summary object for student performance and fee reports.
    Returned by report_service after generating reports.
    """
    total_students: int          # Total number of students processed
    at_risk: int                 # Number of students flagged as "At Risk"
    avg_score: float             # Average total score across all students
    total_fees: float            # Total fees collected
    total_balance: float         # Total outstanding fee balance
    subject_averages: Dict[str, float]  # Average score per subject
    pdf_path: str                # Path to the generated PDF booklet


class StudentFeeRecord(BaseModel):
    """
    Individual student fee record.
    """
    learner_name: str
    fee_paid: float
    fee_balance: float


class FeeSummary(BaseModel):
    """
    Admin-only fee summary response.
    """
    total_fees: float
    total_balance: float
    students: List[StudentFeeRecord]
