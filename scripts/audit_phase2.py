"""Audit the deployed SQLite schema and API contract without modifying data."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys

from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.main import app
from app.core.database import Base
from app.models.api import Scores
from scripts.prepare_migration import inventory, migration_fingerprint


def audit(source, evidence):
    source = source.resolve(strict=True)
    evidence = evidence.resolve(strict=True)
    applied = json.loads((evidence / "applied-result.json").read_text(encoding="utf-8"))
    manifest = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
    rehearsal = json.loads((evidence / "rehearsal-result.json").read_text(encoding="utf-8"))
    expected = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini"))).get_current_head()
    checks = {}
    checks["verified_backup_retained"] = (
        manifest["restore_verified"] and hashlib.sha256((evidence / "verified-backup.sqlite3").read_bytes()).hexdigest() == manifest["backup_sha256"])
    checks["anonymized_rehearsal_verified"] = (
        rehearsal.get("schema_matches_models") is True and rehearsal["revision"] == expected
        and rehearsal["migration_fingerprint"] == migration_fingerprint(ROOT)
        and hashlib.sha256((evidence / "anonymized.sqlite3").read_bytes()).hexdigest() == manifest["anonymized_sha256"]
        and hashlib.sha256((evidence / "rehearsed.sqlite3").read_bytes()).hexdigest() == rehearsal["database_sha256"])
    checks["application_preserved_school_rows"] = applied["original_rows_preserved"] and applied["revision"] == expected
    engine = create_engine("sqlite://", creator=lambda: sqlite3.connect(source.as_uri() + "?mode=ro", uri=True), poolclass=NullPool)
    try:
        with engine.connect() as connection:
            row_counts = inventory(connection.connection.driver_connection)
            checks["sqlite_integrity_and_foreign_keys"] = True  # inventory raises on either failure
            checks["current_revision"] = connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == expected
            for table in ("fees", "marks"):
                checks[f"{table}_have_permanent_ids"] = connection.exec_driver_sql(f"SELECT count(*) FROM {table} WHERE learner_id IS NULL").scalar_one() == 0
            inspector = inspect(connection)
            columns = {column["name"]: column for column in inspector.get_columns("marks")}
            checks["required_mark_identity_and_context"] = all(not columns[field]["nullable"] for field in ("learner_id", "class_name", "academic_year", "term"))
            checks["unique_mark_records"] = any(set(constraint["column_names"]) == {"learner_id", "class_name", "academic_year", "term"} for constraint in inspector.get_unique_constraints("marks"))
            constraints = {item["name"]: re.sub(r"\s+", "", item["sqltext"]).lower() for item in inspector.get_check_constraints("marks")}
            checks["score_bounds_in_database"] = all(constraints.get(f"ck_marks_{field}") == f"{field}>=0and{field}<=100" for field in Scores.model_fields)
            checks["period_bounds_in_database"] = "ck_marks_period" in constraints and "ck_marks_class" in constraints
            checks["unique_retry_receipts"] = any(set(constraint["column_names"]) == {"actor_id", "operation", "key"} for constraint in inspector.get_unique_constraints("request_receipts"))
            checks["schema_matches_models"] = not compare_metadata(MigrationContext.configure(connection, opts={"compare_type": True}), Base.metadata)
    finally:
        engine.dispose()

    schema = app.openapi()
    serialized = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    checks["backend_contract_matches_fastapi"] = (ROOT / "contracts/openapi.json").read_text(encoding="utf-8") == serialized
    frontend_contract = ROOT.parent / "student_reports_frontend/src/generated/openapi.json"
    checks["frontend_contract_matches_fastapi"] = frontend_contract.is_file() and frontend_contract.read_text(encoding="utf-8") == serialized
    components = schema["components"]["schemas"]
    checks["snake_case_json_fields"] = all(re.fullmatch(r"[a-z][a-z0-9_]*", field) for model in components.values() for field in model.get("properties", {}))
    checks["id_based_write_contract"] = {"learner_id", "class_name", "academic_year", "term"}.issubset(components["StudentMarks"]["required"]) and "learner_id" in components["FeeCreate"]["required"]
    checks["required_retry_keys"] = all(any(parameter.get("in") == "header" and parameter["name"] == "Idempotency-Key" and parameter.get("required") for parameter in schema["paths"][path]["post"].get("parameters", [])) for path in ("/marks/submit", "/fees/records/{fee_id}/payments"))
    def resolved(value):
        return components[value["$ref"].split("/")[-1]] if "$ref" in value else value
    checks["paginated_resource_contracts"] = all({"items", "total", "limit", "offset"}.issubset(resolved(schema["paths"][path]["get"]["responses"]["200"]["content"]["application/json"]["schema"])["properties"]) for path in ("/learners", "/marks", "/fees/records/{fee_id}/payments", "/reports/dashboard"))
    return {"audited_at": datetime.now(timezone.utc).isoformat(), "database": str(source),
            "revision": expected, "row_counts": row_counts, "checks": checks, "all_checks_passed": all(checks.values())}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = audit(args.source, args.evidence)
    output = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    print(output)
    raise SystemExit(0 if result["all_checks_passed"] else 1)
