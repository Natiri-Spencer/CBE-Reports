"""Apply rehearsed migrations only while the source still matches its backup."""
import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.prepare_migration import inventory, quote, migration_fingerprint


def apply_verified(source: Path, directory: Path):
    source = source.resolve(strict=True)
    directory = directory.resolve(strict=True)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    result = json.loads((directory / "rehearsal-result.json").read_text(encoding="utf-8"))
    if Path(manifest["source"]).resolve() != source or not manifest.get("restore_verified"):
        raise RuntimeError("The verified backup must belong to the requested source database")
    for filename, digest in (("verified-backup.sqlite3", manifest["backup_sha256"]),
                             ("anonymized.sqlite3", manifest["anonymized_sha256"]),
                             ("rehearsed.sqlite3", result["database_sha256"])):
        if hashlib.sha256((directory / filename).read_bytes()).hexdigest() != digest:
            raise RuntimeError("Migration evidence checksum mismatch")
    configuration = Config(str(ROOT / "alembic.ini"))
    if result["revision"] != ScriptDirectory.from_config(configuration).get_current_head():
        raise RuntimeError("Migrations changed after rehearsal; repeat the anonymized rehearsal first")
    if result.get("migration_fingerprint") != migration_fingerprint(ROOT):
        raise RuntimeError("Migration code changed after rehearsal; repeat the anonymized rehearsal first")
    engine = create_engine("sqlite:///" + source.as_posix(), hide_parameters=True)
    try:
        with engine.begin() as connection, closing(sqlite3.connect((directory / "verified-backup.sqlite3").as_uri() + "?mode=ro", uri=True)) as backup:
            # Lock out concurrent writers before comparing the live committed
            # rows to the verified backup and retain the lock through migration.
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            if inventory(connection.connection.driver_connection) != inventory(backup):
                raise RuntimeError("Source changed since backup; create and rehearse a new backup")
            snapshots = {}
            for table in manifest["row_counts"]:
                if table == "alembic_version":
                    # The revision is migration metadata and must advance;
                    # school rows remain immutable throughout this comparison.
                    continue
                columns = [row[1] for row in backup.execute(f"PRAGMA table_info({quote(table)})")]
                selection = ", ".join(quote(column) for column in columns)
                query = f"SELECT {selection} FROM {quote(table)}"
                rows = Counter(backup.execute(query).fetchall())
                if Counter(tuple(row) for row in connection.exec_driver_sql(query).all()) != rows:
                    raise RuntimeError("Source changed since backup; create and rehearse a new backup")
                snapshots[table] = (columns, rows)
            configuration.attributes["connection"] = connection
            command.upgrade(configuration, "head")
            version = connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
            if version != result["revision"]:
                raise RuntimeError("Applied revision differs from the verified rehearsal")
            inventory(connection.connection.driver_connection)
            for table, (columns, rows) in snapshots.items():
                current_columns = {row[1] for row in connection.exec_driver_sql(f"PRAGMA table_info({quote(table)})")}
                renamed = {"creativeArts": "creative_arts"} if table == "marks" else {}
                selection = ", ".join(quote(renamed.get(column, column) if column not in current_columns else column) for column in columns)
                query = f"SELECT {selection} FROM {quote(table)}"
                if rows - Counter(tuple(row) for row in connection.exec_driver_sql(query).all()):
                    raise RuntimeError("Migration modified or removed pre-existing records; rolling back")
    finally:
        engine.dispose()
    applied = {"applied_at": datetime.now(timezone.utc).isoformat(), "revision": result["revision"],
               "verified_backup_sha256": manifest["backup_sha256"], "original_rows_preserved": True,
               "integrity_check": "ok", "foreign_key_check": "ok"}
    (directory / "applied-result.json").write_text(json.dumps(applied, indent=2) + "\n", encoding="utf-8")
    return applied


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(apply_verified(args.source, args.evidence), indent=2))
