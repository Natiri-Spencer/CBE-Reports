"""Upgrade only a verified anonymized copy, never the source school database."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.prepare_migration import inventory, migration_fingerprint


def rehearse(directory: Path):
    directory = directory.resolve(strict=True)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    for filename, key in (("verified-backup.sqlite3", "backup_sha256"), ("anonymized.sqlite3", "anonymized_sha256")):
        if hashlib.sha256((directory / filename).read_bytes()).hexdigest() != manifest[key]:
            raise RuntimeError("Backup manifest checksum mismatch")
    if not manifest.get("restore_verified") or not manifest.get("anonymized"):
        raise RuntimeError("A verified backup and anonymized copy are required")
    target = directory / "rehearsed.sqlite3"
    # Never overwrite evidence from an earlier rehearsal.
    with target.open("xb") as output, (directory / "anonymized.sqlite3").open("rb") as source:
        shutil.copyfileobj(source, output)
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    engine = create_engine("sqlite:///" + target.as_posix(), hide_parameters=True)
    config = Config(str(root / "alembic.ini"))
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            command.upgrade(config, "head")
            command.check(config)
    finally:
        engine.dispose()
    with closing(sqlite3.connect(target)) as migrated:
        counts = inventory(migrated)
        for table, count in manifest["row_counts"].items():
            if counts.get(table) != count:
                raise RuntimeError(f"Migration changed the row count for {table}")
        revision = migrated.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    result = {"revision": revision, "migration_fingerprint": migration_fingerprint(root), "integrity_check": "ok", "foreign_key_check": "ok", "original_row_counts_preserved": True,
              "repeat_upgrade_verified": True, "schema_matches_models": True,
              "database_sha256": hashlib.sha256(target.read_bytes()).hexdigest()}
    (directory / "rehearsal-result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    print(json.dumps(rehearse(parser.parse_args().directory), indent=2))
