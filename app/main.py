# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from pathlib import Path
from pydantic import BaseModel
import os

from app.routes import reports, auth, marks, fees, admin, learners
from app.core.frontend import mount_frontend
from app.core.validation import request_validation_error

from app.core.operations import lifespan
app = FastAPI(title="Student Reports API", version="2.0", lifespan=lifespan)
app.add_exception_handler(RequestValidationError, request_validation_error)

from app.core.settings import CORS_ORIGINS
from app.core.privacy import PrivateErrors
from app.core.database import get_db
from app.core.backups import backup_is_current
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from fastapi import Depends, HTTPException

app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"])
app.add_middleware(PrivateErrors)

# Routers
app.include_router(reports.router, prefix="/reports", tags=["Reports"])
app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(marks.router, prefix="/marks", tags=["Marks"])
app.include_router(fees.router, prefix="/fees", tags=["Fees"])
app.include_router(admin.router, prefix="/admin", tags=["Admin"])
app.include_router(learners.router, prefix="/learners", tags=["Learners"])


class HealthResponse(BaseModel):
    status: str


@app.get("/health", response_model=HealthResponse, tags=["Operations"], operation_id="health")
def health_check():
    return {"status": "ok"}


@app.get("/ready", response_model=HealthResponse, tags=["Operations"], operation_id="readiness")
def readiness(db=Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        revision = db.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        expected = ScriptDirectory.from_config(Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))).get_current_head()
        if revision != expected or not backup_is_current():
            raise RuntimeError("not ready")
    except Exception:
        raise HTTPException(503, "Not ready") from None
    return {"status": "ready"}


# Serve React build in PROD if available
ENV = os.getenv("ENV", "DEV").upper()

if ENV == "PROD":
    project_root = Path(__file__).resolve().parents[2]
    react_build_path = project_root / "student_reports_frontend" / "build"

    if (react_build_path / "index.html").is_file():


        mount_frontend(app, react_build_path)
    else:
        pass
