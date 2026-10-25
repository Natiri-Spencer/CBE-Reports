import unittest
from importlib import import_module
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import init_db
from app.models.fee import Fee, FeePayment


class DatabaseMigrationTests(unittest.TestCase):
    def test_restart_preserves_legacy_balances_without_duplicating_payments(self):
        engine = create_engine("sqlite://")
        try:
            metadata = import_module("migrations.versions.0001_legacy_baseline").legacy_metadata()
            metadata.create_all(engine)
            with engine.begin() as connection:
                fees = metadata.tables["fees"]
                legacy_id = connection.execute(fees.insert().values(learner_name="Legacy", grade="7", school_required=1000, school_fee=100)).inserted_primary_key[0]
                current_id = connection.execute(fees.insert().values(learner_name="Current", grade="7", school_required=1000, school_fee=250)).inserted_primary_key[0]
                connection.execute(metadata.tables["fee_payments"].insert().values(fee_id=current_id, category="school", amount=250, is_opening_balance=False, created_at=datetime.now(timezone.utc)))
            init_db(engine)
            init_db(engine)
            with Session(engine) as db:
                payments = db.query(FeePayment).all()
                self.assertEqual(len(payments), 2)
                self.assertEqual(sum(p.amount for p in payments if p.fee_id == legacy_id), 100)
                self.assertEqual(sum(p.amount for p in payments if p.fee_id == current_id), 250)
                self.assertEqual(sum(p.is_opening_balance for p in payments), 1)
        finally:
            engine.dispose()
