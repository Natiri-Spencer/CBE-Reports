"""Create and verify a consistent SQLite backup and an anonymized rehearsal copy.

The source is opened read-only. No application modules or startup hooks are run.
"""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
from datetime import datetime, timezone
from uuid import uuid4


def quote(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def migration_fingerprint(root: Path):
    digest = hashlib.sha256()
    paths = [root / "alembic.ini", *sorted((root / "migrations").rglob("*.py"))]
    for path in paths:
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def inventory(connection):
    if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise RuntimeError("SQLite integrity check failed")
    if connection.execute("PRAGMA foreign_key_check").fetchall():
        raise RuntimeError("SQLite foreign key check failed")
    tables = [row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )]
    return {table: connection.execute(f"SELECT count(*) FROM {quote(table)}").fetchone()[0] for table in tables}


def anonymize(connection):
    tables = inventory(connection)
    allowed = {"marks", "fees", "users", "fee_payments", "admin_activity", "alembic_version", "learners", "request_receipts", "auth_sessions", "refresh_tokens", "login_attempts"}
    if set(tables) - allowed:
        raise RuntimeError("Unknown tables require an explicit anonymization rule")
    names = set()
    for table, field in (("marks", "name"), ("fees", "learner_name"), ("learners", "name")):
        if table in tables:
            names.update(row[0].strip() for row in connection.execute(f"SELECT {field} FROM {table}") if row[0] is not None and row[0].strip())
    mapping = {name: f"Learner {index:06d}" for index, name in enumerate(sorted(names), 1)}
    for table, field in (("marks", "name"), ("fees", "learner_name"), ("learners", "name")):
        if table in tables:
            # Update by row ID so a generated label cannot collide with another original name.
            for row_id, name in connection.execute(f"SELECT id, {field} FROM {table}").fetchall():
                replacement = mapping.get(name.strip(), name) if name is not None else None
                connection.execute(f"UPDATE {table} SET {field}=? WHERE id=?", (replacement, row_id))
    if "users" in tables:
        connection.execute("UPDATE users SET username='test-user-' || id, hashed_password='!disabled-for-migration-rehearsal!'")
    if "auth_sessions" in tables:
        connection.execute("UPDATE auth_sessions SET revoked_at=0")
    if "refresh_tokens" in tables:
        for index, (digest,) in enumerate(connection.execute("SELECT digest FROM refresh_tokens").fetchall()):
            connection.execute("UPDATE refresh_tokens SET digest=?, consumed_at=0 WHERE digest=?", (hashlib.sha256(f"anonymous-{index}".encode()).hexdigest(), digest))
    if "login_attempts" in tables:
        connection.execute("UPDATE login_attempts SET account_key='anonymous', client_key='anonymous'")
    if "fee_payments" in tables:
        connection.execute("UPDATE fee_payments SET reference=NULL, note=NULL")
    if "admin_activity" in tables:
        connection.execute("UPDATE admin_activity SET actor_username='test-actor', entity_id=NULL, description='Anonymized activity'")
    if "request_receipts" in tables:
        connection.execute("UPDATE request_receipts SET key='anonymous-request-' || id, response_body='{}', request_hash='anonymized'")
    if "learners" in tables:
        # The rehearsal must not expose the real permanent IDs either. The
        # private backup retains them; all references in this copy move together.
        for (old_id,) in connection.execute("SELECT id FROM learners").fetchall():
            new_id = str(uuid4())
            connection.execute("UPDATE learners SET id=? WHERE id=?", (new_id, old_id))
            for table in ("fees", "marks"):
                if table in tables:
                    connection.execute(f"UPDATE {table} SET learner_id=? WHERE learner_id=?", (new_id, old_id))
    connection.commit()
    connection.execute("VACUUM")  # Remove original text from free pages as well.
    return inventory(connection)


def prepare(source: Path, output: Path):
    source = source.resolve(strict=True)
    output.mkdir(parents=True, exist_ok=False)
    backup_path = output / "verified-backup.sqlite3"
    anonymous_path = output / "anonymized.sqlite3"
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original:
        inventory(original)
        with closing(sqlite3.connect(backup_path)) as backup:
            original.backup(backup)
    # Reopen and restore the backup to prove it can actually be restored.
    with closing(sqlite3.connect(backup_path)) as backup, closing(sqlite3.connect(":memory:")) as restored:
        counts = inventory(backup)
        backup.backup(restored)
        if inventory(restored) != counts:
            raise RuntimeError("Restored row counts do not match the backup")
        with closing(sqlite3.connect(anonymous_path)) as anonymous:
            backup.backup(anonymous)
            if anonymize(anonymous) != counts:
                raise RuntimeError("Anonymization changed row counts")
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": str(source),
        "backup_sha256": hashlib.sha256(backup_path.read_bytes()).hexdigest(),
        "anonymized_sha256": hashlib.sha256(anonymous_path.read_bytes()).hexdigest(),
        "row_counts": counts,
        "integrity_check": "ok", "foreign_key_check": "ok", "restore_verified": True,
        "anonymized": True,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.source, args.output), indent=2))
