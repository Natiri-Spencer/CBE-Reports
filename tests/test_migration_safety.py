import os as _os
import secrets as _secrets
_os.environ.setdefault("JWT_SECRET_KEY", _secrets.token_urlsafe(48))
from hashlib import sha256
from contextlib import closing
from importlib import import_module
from pathlib import Path
import sqlite3
from datetime import datetime, timezone
from tempfile import TemporaryDirectory
import unittest

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.core.database import init_db
from scripts.prepare_migration import prepare
from scripts.rehearse_migration import rehearse
from scripts.apply_verified_migration import apply_verified


class MigrationSafetyTests(unittest.TestCase):
    def test_verified_upgrade_of_an_already_versioned_database_preserves_zero_marks(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "versioned.sqlite3"
            engine = create_engine("sqlite:///" + source.as_posix())
            configuration = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
            with engine.begin() as db:
                configuration.attributes["connection"] = db
                command.upgrade(configuration, "0002_permanent_learner_ids")
                db.execute(text("INSERT INTO learners (id,name,class_name,created_at) VALUES (:id,'Test Learner','7',:now)"),
                           {"id": "11111111-1111-4111-8111-111111111111", "now": datetime.now(timezone.utc)})
                db.execute(text('INSERT INTO marks (name,learner_id,mathematics,pretechnical,cre,agriculture,integrated_science,social_studies,english,kiswahili,"creativeArts",total,average,status,rank) VALUES (\'Test Learner\',:id,0,0,0,0,0,0,0,0,0,0,0,\'BE2\',1)'),
                           {"id": "11111111-1111-4111-8111-111111111111"})
            engine.dispose()
            evidence = Path(directory) / "evidence"
            prepare(source, evidence)
            rehearsal = rehearse(evidence)
            self.assertTrue(rehearsal["schema_matches_models"])
            apply_verified(source, evidence)
            with closing(sqlite3.connect(source)) as db:
                self.assertEqual(db.execute("SELECT learner_id,class_name,academic_year,term,creative_arts,status FROM marks").fetchone(),
                    ("11111111-1111-4111-8111-111111111111", "7", 0, 0, 0, "BE2"))
                self.assertEqual(db.execute("SELECT version_num FROM alembic_version").fetchone()[0], rehearsal["revision"])

    def test_verified_application_preserves_data_and_rejects_stale_backups(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "source.sqlite3"
            engine = create_engine("sqlite:///" + source.as_posix())
            metadata = import_module("migrations.versions.0001_legacy_baseline").legacy_metadata()
            metadata.create_all(engine)
            with engine.begin() as db:
                db.execute(metadata.tables["fees"].insert().values(learner_name="Test Learner", grade="7", school_required=1000))
            engine.dispose()
            first = Path(directory) / "first"
            prepare(source, first)
            rehearse(first)
            with closing(sqlite3.connect(source)) as db, db:
                db.execute("UPDATE fees SET school_required=2000")
            with self.assertRaisesRegex(RuntimeError, "changed since backup"):
                apply_verified(source, first)
            second = Path(directory) / "second"
            prepare(source, second)
            rehearse(second)
            result = apply_verified(source, second)
            self.assertTrue(result["original_rows_preserved"])
            with closing(sqlite3.connect(source)) as db:
                self.assertEqual(db.execute("SELECT school_required FROM fees").fetchone()[0], 2000)
                self.assertEqual(len(db.execute("SELECT learner_id FROM fees").fetchone()[0]), 36)

    def test_backup_restores_and_anonymization_removes_source_text(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "source.sqlite3"
            with closing(sqlite3.connect(source)) as db, db:
                db.execute("CREATE TABLE marks (id INTEGER PRIMARY KEY, name TEXT)")
                db.executemany("INSERT INTO marks VALUES (?, ?)", [(1, " Private Learner "), (2, "Private Learner"), (3, "   ")])
            before = sha256(source.read_bytes()).hexdigest()
            result = prepare(source, Path(directory) / "backup")
            self.assertTrue(result["restore_verified"])
            self.assertEqual(before, sha256(source.read_bytes()).hexdigest())
            anonymous = Path(directory) / "backup" / "anonymized.sqlite3"
            self.assertNotIn(b"Private Learner", anonymous.read_bytes())
            with closing(sqlite3.connect(anonymous)) as db:
                names = [row[0] for row in db.execute("SELECT name FROM marks ORDER BY id")]
                self.assertEqual(names[0], names[1])
                self.assertEqual(names[2], "   ")  # Do not disguise invalid source data.

    def test_identity_migration_preserves_rows_and_ids_across_retries(self):
        engine = create_engine("sqlite://")
        metadata = import_module("migrations.versions.0001_legacy_baseline").legacy_metadata()
        try:
            metadata.create_all(engine)
            with engine.begin() as db:
                db.execute(metadata.tables["fees"].insert().values(learner_name="Test Learner", grade="7", school_required=1000))
                db.execute(metadata.tables["marks"].insert().values(name="Test Learner", mathematics=0))
            init_db(engine)
            with engine.connect() as db:
                mark_id = db.execute(text("SELECT learner_id FROM marks")).scalar_one()
                fee_id = db.execute(text("SELECT learner_id FROM fees")).scalar_one()
                self.assertEqual(mark_id, fee_id)
                self.assertEqual(len(mark_id), 36)
                self.assertEqual(db.execute(text("SELECT mathematics FROM marks")).scalar_one(), 0)
            init_db(engine)
            with engine.connect() as db:
                self.assertEqual(db.execute(text("SELECT id FROM learners")).scalar_one(), mark_id)
        finally:
            engine.dispose()

    def test_ambiguous_identity_rolls_back_schema_and_data_together(self):
        engine = create_engine("sqlite://")
        configuration = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        try:
            with engine.begin() as db:
                configuration.attributes["connection"] = db
                command.upgrade(configuration, "0001_legacy_baseline")
            with engine.begin() as db:
                db.execute(text("INSERT INTO marks (name) VALUES ('Same Name')"))
                fees = import_module("migrations.versions.0001_legacy_baseline").legacy_metadata().tables["fees"]
                for grade in ("7", "8"):
                    db.execute(fees.insert().values(learner_name="Same Name", grade=grade, school_required=0))
            with self.assertRaisesRegex(RuntimeError, "ambiguous"):
                init_db(engine)
            with engine.connect() as db:
                self.assertNotIn("learners", inspect(db).get_table_names())
                self.assertNotIn("learner_id", {column["name"] for column in inspect(db).get_columns("marks")})
                self.assertEqual(db.execute(text("SELECT count(*) FROM marks")).scalar_one(), 1)
                self.assertEqual(db.execute(text("SELECT version_num FROM alembic_version")).scalar_one(), "0001_legacy_baseline")
        finally:
            engine.dispose()
