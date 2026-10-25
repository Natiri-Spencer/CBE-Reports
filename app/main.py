# app/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import os

from app.routes import reports, auth, marks, fees, admin
from app.core.database import init_db
from app.core.frontend import mount_frontend

# Initialize DB tables
init_db()

app = FastAPI(title="Student Reports API", version="1.0")

# Explicit origins are required when credentials are enabled. Configure
# deployed web origins through CORS_ORIGINS as a comma-separated list.
cors_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(reports.router, prefix="/reports", tags=["Reports"])
app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(marks.router, prefix="/marks", tags=["Marks"])
app.include_router(fees.router, prefix="/fees", tags=["Fees"])
app.include_router(admin.router, prefix="/admin", tags=["Admin"])


@app.get("/health", tags=["Operations"])
def health_check():
    return {"status": "ok"}


# Serve React build in PROD if available
ENV = os.getenv("ENV", "DEV").upper()

if ENV == "PROD":
    project_root = Path(__file__).resolve().parents[3]
    react_build_path = project_root / "student_reports_frontend" / "build"

    if (react_build_path / "index.html").is_file():
        print(f"[DEBUG] Serving React build from: {react_build_path.resolve()}")

        mount_frontend(app, react_build_path)
    else:
        print("[ERROR] React build path not found. Please check your build directory.")
