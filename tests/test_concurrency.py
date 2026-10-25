import os as _os
import secrets as _secrets
_os.environ.setdefault("JWT_SECRET_KEY", _secrets.token_urlsafe(48))
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.core.auth import issue_tokens
from app.core.passwords import hash_password
from app.models.security import AuthSession, RefreshToken, LoginAttempt
from app.core.database import Base, get_db
from app.main import app
from app.models.admin_activity import AdminActivity
from app.models.fee import Fee, FeePayment
from app.models.learner import Learner
from app.models.marks import Marks
from app.models.request_receipt import RequestReceipt
from app.models.user import User
from app.models.api import Scores


class ConcurrentMutationTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        database = Path(self.directory.name) / "concurrency.sqlite3"
        self.engine = create_engine("sqlite:///" + database.as_posix(), poolclass=NullPool,
                                    connect_args={"check_same_thread": False, "timeout": 20})
        @event.listens_for(self.engine, "connect")
        def foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, autoflush=False)
        with self.Session() as db:
            db.add_all([User(username="admin", hashed_password="unused", role="admin"),
                        User(username="teacher", hashed_password="unused", role="teacher")])
            learners = [Learner(name=f"Test {index}", class_name="7") for index in range(6)]
            db.add_all(learners)
            db.flush()
            self.learner_ids = [learner.id for learner in learners]
            fee = Fee(learner_id=learners[0].id, learner_name=learners[0].name, grade="7",
                      academic_year=2026, term=3, school_required=10000)
            db.add(fee)
            db.commit()
            self.fee_id = fee.id
        def test_db():
            with self.Session() as db:
                yield db
        app.dependency_overrides[get_db] = test_db
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        self.engine.dispose()
        self.directory.cleanup()

    def token(self, username):
        with self.Session() as db:
            result = issue_tokens(db, db.query(User).filter_by(username=username).one())
            db.commit()
            return result["access_token"]

    def concurrent(self, make_request):
        barrier = Barrier(6)
        def invoke(index):
            barrier.wait(timeout=20)
            return make_request(index)
        with ThreadPoolExecutor(max_workers=6) as executor:
            results = list(executor.map(invoke, range(6)))
        for response in results:
            self.assertEqual(response.status_code, 200, response.text)
        return results

    def test_simultaneous_retries_create_exactly_one_payment_and_receipt(self):
        token = self.token("admin")
        request_headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": "same-payment"}
        responses = self.concurrent(lambda _: self.client.post(f"/fees/records/{self.fee_id}/payments", headers=request_headers,
            json={"category": "school", "amount": 250, "payment_date": "2026-10-25"}))
        self.assertEqual(len({response.json()["id"] for response in responses}), 1)
        with self.Session() as db:
            self.assertEqual(db.query(FeePayment).count(), 1)
            self.assertEqual(db.query(RequestReceipt).count(), 1)
            self.assertEqual(db.query(AdminActivity).count(), 1)
            self.assertEqual(db.get(Fee, self.fee_id).total_paid, 250)

    def test_distinct_concurrent_payments_never_lose_balance_updates(self):
        token = self.token("admin")
        self.concurrent(lambda index: self.client.post(f"/fees/records/{self.fee_id}/payments",
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": f"payment-{index}"},
            json={"category": "school", "amount": 100 * (index + 1), "payment_date": "2026-10-25"}))
        with self.Session() as db:
            self.assertEqual(db.query(FeePayment).count(), 6)
            fee = db.get(Fee, self.fee_id)
            self.assertEqual(fee.school_fee, 2100)
            self.assertEqual(fee.total_paid, 2100)
            self.assertEqual(fee.total_balance, 7900)

    def test_concurrent_mark_submissions_preserve_unique_rows_and_class_rankings(self):
        token = self.token("teacher")
        def submit(index):
            return self.client.post("/marks/submit", headers={"Authorization": f"Bearer {token}", "Idempotency-Key": f"marks-{index}"},
                json={"students": [{"learner_id": self.learner_ids[index], "class_name": "7", "academic_year": 2026, "term": 3,
                                    **{field: 60 + index for field in Scores.model_fields}}]})
        self.concurrent(submit)
        with self.Session() as db:
            rows = db.query(Marks).order_by(Marks.rank).all()
            self.assertEqual(len(rows), 6)
            self.assertEqual([row.rank for row in rows], list(range(1, 7)))
            self.assertEqual([row.average for row in rows], [65, 64, 63, 62, 61, 60])

    def test_simultaneous_mark_retries_create_one_record_and_one_receipt(self):
        token = self.token("teacher")
        body = {"students": [{"learner_id": self.learner_ids[0], "class_name": "7", "academic_year": 2026, "term": 3,
                              **{field: 0 for field in Scores.model_fields}}]}
        responses = self.concurrent(lambda _: self.client.post("/marks/submit",
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "same-marks"}, json=body))
        self.assertTrue(all(response.json() == responses[0].json() for response in responses))
        with self.Session() as db:
            self.assertEqual(db.query(Marks).count(), 1)
            self.assertEqual(db.query(RequestReceipt).count(), 1)
            self.assertEqual(db.query(Marks).one().status, "BE2")
