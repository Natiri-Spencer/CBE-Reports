"""Encrypted SQLite backups with a real restore verification on every run."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from tempfile import TemporaryDirectory
import time
from uuid import uuid4
from cryptography.fernet import Fernet
from app.core.settings import ROOT
from app.core.database import engine
from scripts.prepare_migration import inventory

BACKUP_DIRECTORY = Path(os.getenv("BACKUP_DIRECTORY", str(ROOT / ".local" / "backups"))).resolve()
RETENTION_DAYS = 14

def cipher():
    key = os.getenv("BACKUP_ENCRYPTION_KEY", "")
    if not key:
        raise RuntimeError("Configure an independent BACKUP_ENCRYPTION_KEY before backing up")
    return Fernet(key.encode())

def source_path():
    if engine.dialect.name != "sqlite" or not engine.url.database or engine.url.database == ":memory:":
        raise RuntimeError("Backups require the configured file-backed SQLite database")
    return Path(engine.url.database).resolve(strict=True)

def restore_file(encrypted_path, destination):
    destination = Path(destination).resolve()
    if destination.exists():
        raise RuntimeError("Restore destination must not exist")
    data = cipher().decrypt(Path(encrypted_path).read_bytes())
    with closing(sqlite3.connect(":memory:")) as restored:
        restored.deserialize(data)
        counts = inventory(restored)
        # Restoring a historical database must never resurrect revoked sessions.
        if "auth_sessions" in counts:
            restored.execute("UPDATE auth_sessions SET revoked_at=?", (int(time.time()),))
            restored.execute("UPDATE refresh_tokens SET consumed_at=?", (int(time.time()),))
        if "users" in counts and "token_version" in {row[1] for row in restored.execute("PRAGMA table_info(users)")}:
            restored.execute("UPDATE users SET token_version=token_version+1")
        restored.commit()
        # Exclusive creation prevents accidental overwrite even under a race.
        with destination.open("xb") as output:
            output.write(restored.serialize())
            output.flush()
            os.fsync(output.fileno())
    with closing(sqlite3.connect(destination.as_uri() + "?mode=ro", uri=True)) as reopened:
        if inventory(reopened) != counts:
            raise RuntimeError("Restored row counts differ")
    return counts

def backup():
    BACKUP_DIRECTORY.mkdir(parents=True, exist_ok=True)
    source = source_path()
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original, closing(sqlite3.connect(":memory:")) as snapshot:
        original.backup(snapshot)
        counts = inventory(snapshot)
        encrypted = cipher().encrypt(snapshot.serialize())
    name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ_") + uuid4().hex + ".backup"
    target = BACKUP_DIRECTORY / name
    with target.open("xb") as output:
        output.write(encrypted)
        output.flush()
        os.fsync(output.fileno())
    try:
        with TemporaryDirectory(prefix="restore-test-", dir=BACKUP_DIRECTORY) as temporary:
            if restore_file(target, Path(temporary) / "restored.sqlite3") != counts:
                raise RuntimeError("Backup restore verification failed")
        result = {"created_at": int(time.time()), "file": name,
                  "sha256": hashlib.sha256(encrypted).hexdigest(), "restore_verified": True,
                  "key_id": hashlib.sha256(os.environ["BACKUP_ENCRYPTION_KEY"].encode()).hexdigest(),
                  "source_id": hashlib.sha256(str(source).encode()).hexdigest(),
                  "row_counts": counts, "integrity_check": "ok", "foreign_key_check": "ok"}
        temporary_manifest = BACKUP_DIRECTORY / (uuid4().hex + ".tmp")
        temporary_manifest.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        temporary_manifest.replace(BACKUP_DIRECTORY / "latest.json")
        # Only remove this tool's old encrypted snapshots after verifying a new one.
        for old in BACKUP_DIRECTORY.iterdir():
            if re.fullmatch(r"\d{8}T\d{6}Z_[0-9a-f]{32}\.backup", old.name) and not old.is_symlink():
                if old != target and old.stat().st_mtime < time.time() - RETENTION_DAYS * 86400:
                    old.unlink()
        return result
    except Exception:
        target.unlink(missing_ok=True)
        raise

def backup_is_current():
    try:
        result = json.loads((BACKUP_DIRECTORY / "latest.json").read_text(encoding="utf-8"))
        name = result["file"]
        return (Path(name).name == name and result["restore_verified"] is True
                and 0 <= time.time() - result["created_at"] < 36 * 3600
                and result["key_id"] == hashlib.sha256(os.environ.get("BACKUP_ENCRYPTION_KEY", "").encode()).hexdigest()
                and result["source_id"] == hashlib.sha256(str(source_path()).encode()).hexdigest()
                and hashlib.sha256((BACKUP_DIRECTORY / name).read_bytes()).hexdigest() == result["sha256"])
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        return False
