from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
import os

from app.routes import reports, auth, marks

app = FastAPI(title="Student Reports API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(reports.router, prefix="/reports", tags=["Reports"])
app.include_router(auth.router, prefix="/auth", tags=["Auth"])
app.include_router(marks.router, prefix="/marks", tags=["Marks"])

ENV = os.getenv("ENV", "DEV")

if ENV == "PROD":
    react_build_path = Path("C:/Users/Administrator/Desktop/Grade  Tool/student_reports_frontend/build")

    # ✅ Debug print
    print(f"[DEBUG] Serving React build from: {react_build_path.resolve()}")

    # Serve static files
    app.mount("/static", StaticFiles(directory=react_build_path / "static"), name="static")

    # Serve React index.html at root
    @app.get("/", response_class=FileResponse)
    async def serve_home():
        print("[DEBUG] Serving homepage index.html")
        return react_build_path / "index.html"

    # Catch-all route for React Router
    @app.get("/{full_path:path}", response_class=FileResponse)
    async def serve_react_router(full_path: str):
        print(f"[DEBUG] React router caught path: /{full_path}")
        return react_build_path / "index.html"
