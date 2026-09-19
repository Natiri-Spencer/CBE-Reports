from fastapi import APIRouter, UploadFile, File, HTTPException
from app.services import report_service
from app.models.schemas import ReportSummary

router = APIRouter()

@router.post("/generate", response_model=ReportSummary)
async def generate_reports(performance: UploadFile = File(...), fees: UploadFile = File(...)):
    """
    Upload performance.csv and fees.csv to generate reports and PDF booklet.
    """
    try:
        # Reset file pointers so pandas can read from the beginning
        performance.file.seek(0)
        fees.file.seek(0)

        # Call the service layer
        summary = report_service.generate_reports(performance.file, fees.file)

        # Return the structured summary JSON
        return summary
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/summary", response_model=ReportSummary)
async def get_summary():
    """
    Get summary of last generated reports.
    """
    return report_service.get_last_summary()
