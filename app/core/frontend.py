"""Serve the Vite build and React routes from the production API."""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


def mount_frontend(app: FastAPI, build_path: Path) -> None:
    build_path = build_path.resolve()
    if (build_path / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=build_path / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend(full_path: str):
        ui_routes = {"admin", "admin/finance"}
        api_prefixes = {"auth", "marks", "fees", "reports", "admin", "learners", "health", "ready", "docs", "redoc", "openapi.json"}
        if full_path not in ui_routes and full_path.split("/", 1)[0] in api_prefixes:
            raise HTTPException(status_code=404, detail="Not found")
        candidate = (build_path / full_path).resolve()
        if not candidate.is_relative_to(build_path):
            raise HTTPException(status_code=404, detail="Not found")
        if candidate.is_file():
            return FileResponse(candidate)
        if Path(full_path).suffix:
            raise HTTPException(status_code=404, detail="Not found")
        return FileResponse(build_path / "index.html")
