"""Export the authoritative schema and the frontend copy; --check detects drift."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.main import app


def export(check=False):
    output = json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"
    destinations = [ROOT / "contracts" / "openapi.json"]
    frontend = ROOT.parent / "student_reports_frontend"
    if (frontend / "package.json").is_file():
        destinations.append(frontend / "src" / "generated" / "openapi.json")
    for destination in destinations:
        if check:
            if not destination.is_file() or destination.read_text(encoding="utf-8") != output:
                raise SystemExit(f"OpenAPI contract is out of date: {destination}")
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(output, encoding="utf-8")
    print("OpenAPI contract matches FastAPI and the frontend" if check else "Exported FastAPI OpenAPI contract to backend and frontend")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    export(parser.parse_args().check)
