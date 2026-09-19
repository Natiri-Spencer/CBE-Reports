from pydantic import BaseModel
from typing import Dict

class ReportSummary(BaseModel):
    total_students: int
    at_risk: int
    avg_score: float
    total_fees: float
    total_balance: float
    subject_averages: Dict[str, float]
    pdf_path: str  # new field
