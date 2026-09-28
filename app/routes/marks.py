from fastapi import APIRouter
from pydantic import BaseModel
from typing import List
from app.services.report_service import grade_comment

router = APIRouter()

# Student model with all subjects
class StudentMarks(BaseModel):
    name: str
    mathematics: int
    pretechnical: int
    cre: int
    agriculture: int
    integrated_science: int
    social_studies: int
    english: int
    kiswahili: int
    creative_arts: int

class MarksSubmission(BaseModel):
    students: List[StudentMarks]

@router.post("/submit")
def submit_marks(data: MarksSubmission):
    results = []
    for student in data.students:
        subjects = student.dict(exclude={"name"})
        total = sum(subjects.values())
        average = total / len(subjects)
        status = "ME" if average >= 60 else "AE"

        # Add comments for each subject
        comments = {f"{subj}_comment": grade_comment(score) for subj, score in subjects.items()}

        results.append({
            "name": student.name,
            "total": total,
            "average": average,
            "status": status,
            **subjects,
            **comments
        })
    return {"results": results}
