import os as _os
import secrets as _secrets
_os.environ.setdefault("JWT_SECRET_KEY", _secrets.token_urlsafe(48))
import csv
import io
import json
import os
from pathlib import Path
import unittest
from uuid import uuid4

os.environ["DATABASE_URL"] = "sqlite://"
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.exc import IntegrityError

from app.core.database import Base, get_db
from app.core.auth import issue_tokens
from app.core.passwords import hash_password
from app.models.security import AuthSession, RefreshToken, LoginAttempt
from app.main import app
from app.models.user import User
from app.models.learner import Learner
from app.models.marks import Marks
from app.models.fee import Fee, FeePayment
from app.models.request_receipt import RequestReceipt
from app.models.admin_activity import AdminActivity
from app.models.api import Scores

FIXTURES = Path(__file__).parent / "fixtures"


def headers(token, key=None):
    return {"Authorization": f"Bearer {token}", "Idempotency-Key": key or str(uuid4())}


def mark_payload(learner_id, **changes):
    row = json.loads((FIXTURES / "marks_submission.json").read_text())["students"][0]
    row.update(learner_id=learner_id)
    row.update(changes)
    return row


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        @event.listens_for(cls.engine, "connect")
        def foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")
        cls.Session = sessionmaker(bind=cls.engine, autoflush=False)
        Base.metadata.create_all(cls.engine)
        def test_db():
            with cls.Session() as db:
                yield db
        app.dependency_overrides[get_db] = test_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        app.dependency_overrides.clear()
        cls.engine.dispose()

    def setUp(self):
        with self.Session() as db:
            for model in (RefreshToken, AuthSession, LoginAttempt, RequestReceipt, FeePayment, AdminActivity, Fee, Marks, Learner, User):
                db.query(model).delete()
            db.commit()

    def teacher_token(self):
        with self.Session() as db:
            db.add(User(username="teacher1", hashed_password=hash_password("testing-password"), role="teacher"))
            db.commit()
        response = self.client.post("/auth/token", data={"username": "teacher1", "password": "testing-password"})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["access_token"]

    def admin_token(self):
        with self.Session() as db:
            db.add(User(username="admin1", hashed_password="unused", role="admin"))
            db.commit()
        with self.Session() as db:
            result = issue_tokens(db, db.query(User).filter_by(username="admin1").one())
            db.commit()
            return result["access_token"]

    def learner(self, token, name="Test Learner", class_name="7"):
        response = self.client.post("/learners", headers=headers(token), json={"name": name, "class_name": class_name})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    def fee(self, token, learner_id):
        response = self.client.post("/fees", headers=headers(token), json={"learner_id": learner_id, "grade": "7", "academic_year": 2026, "term": 3, "school_required": 1000})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def submit(self, token, rows, key=None):
        return self.client.post("/marks/submit", headers=headers(token, key), json={"students": rows})

    def test_health_and_access_controls(self):
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})
        self.assertEqual(self.client.get("/marks").status_code, 401)
        self.assertEqual(self.client.get("/learners").status_code, 401)
        token = self.teacher_token()
        self.assertEqual(self.client.get("/admin/dashboard", headers=headers(token)).status_code, 403)

    def test_permanent_learner_ids_pagination_and_create_retry(self):
        token = self.teacher_token()
        ids = [self.learner(token, " Same Name ") for _ in range(3)]
        self.assertEqual(len(set(ids)), 3)
        first = self.client.get("/learners?limit=2&offset=0", headers=headers(token)).json()
        self.assertTrue(first["items"][0]["created_at"].endswith("Z"))
        second = self.client.get("/learners?limit=2&offset=2", headers=headers(token)).json()
        self.assertEqual(first["total"], 3)
        self.assertEqual({row["id"] for row in first["items"] + second["items"]}, set(ids))
        self.assertEqual(len(first["items"]), 2)
        self.assertEqual(self.client.get(f"/learners/{ids[0]}", headers=headers(token)).json()["id"], ids[0])
        for path in ("/learners?limit=201", "/learners?offset=-1"):
            self.assertEqual(self.client.get(path, headers=headers(token)).status_code, 422)
        request_headers = headers(token)
        body = {"name": "Retry Learner", "class_name": "7"}
        first = self.client.post("/learners", headers=request_headers, json=body)
        self.assertEqual(self.client.post("/learners", headers=request_headers, json=body).json(), first.json())

    def test_marks_are_canonical_and_retry_does_not_overwrite_a_later_update(self):
        token = self.teacher_token()
        learner_id = self.learner(token)
        row = mark_payload(learner_id, **{field: 67.8 for field in Scores.model_fields})
        first = self.submit(token, [row], "first-request")
        self.assertEqual(first.status_code, 200, first.text)
        record = first.json()["results"][0]
        self.assertEqual(record["status"], "EE2")
        self.assertIn("creative_arts", record)
        self.assertNotIn("creativeArts", record)
        updated = self.submit(token, [{**row, "mathematics": 0}], "second-request")
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["results"][0]["id"], record["id"])
        self.assertEqual(self.submit(token, [row], "first-request").json(), first.json())
        self.assertEqual(self.submit(token, [{**row, "mathematics": 99}], "first-request").status_code, 409)
        with self.Session() as db:
            self.assertEqual(db.query(Marks).count(), 1)
            self.assertEqual(db.query(Marks).one().mathematics, 0)
        rows = list(csv.DictReader(io.StringIO(self.client.get("/marks/export?academic_year=2026&term=3", headers=headers(token)).text)))
        self.assertEqual(rows[0]["Learner ID"], learner_id)
        self.assertEqual(rows[0]["Mathematics Comment"], "BE2")

    def test_namesakes_terms_classes_and_rankings_are_independent(self):
        token = self.teacher_token()
        first = self.learner(token, "Same Name")
        second = self.learner(token, "Same Name")
        rows = [mark_payload(first, term=1), mark_payload(first, **{field: 90 for field in Scores.model_fields}),
                mark_payload(second, **{field: 80 for field in Scores.model_fields}),
                mark_payload(first, class_name="8", **{field: 100 for field in Scores.model_fields})]
        response = self.submit(token, rows)
        self.assertEqual(response.status_code, 200, response.text)
        page = self.client.get("/marks?academic_year=2026&term=3&class_name=7", headers=headers(token)).json()
        self.assertEqual(page["total"], 2)
        self.assertEqual([(row["learner_id"], row["rank"]) for row in page["items"]], [(first, 1), (second, 2)])
        earlier = self.client.get("/marks?academic_year=2026&term=1", headers=headers(token)).json()
        self.assertEqual(earlier["total"], 1)
        self.assertEqual(earlier["items"][0]["rank"], 1)

    def test_invalid_or_partial_bulk_requests_do_not_save_any_marks(self):
        token = self.teacher_token()
        learner_id = self.learner(token)
        row = mark_payload(learner_id)
        for rows in ([], [row, row], [{**row, "name": "Name based write"}], [{**row, "term": 0}], [{**row, "mathematics": "Infinity"}]):
            self.assertEqual(self.submit(token, rows).status_code, 422)
        missing = self.client.post("/marks/submit", headers={"Authorization": f"Bearer {token}"}, json={"students": [row]})
        self.assertEqual(missing.status_code, 422)
        response = self.submit(token, [row, mark_payload(str(uuid4()))], "atomic-batch")
        self.assertEqual(response.status_code, 404, response.text)
        with self.Session() as db:
            self.assertEqual(db.query(Marks).count(), 0)
            self.assertEqual(db.query(RequestReceipt).filter_by(key="atomic-batch").count(), 0)

    def test_overflowing_json_score_returns_a_validation_error(self):
        token = self.teacher_token()
        learner_id = self.learner(token)
        body = json.dumps({"students": [mark_payload(learner_id)]}).replace('"mathematics": 80', '"mathematics": 1e999')
        response = self.client.post("/marks/submit", headers={**headers(token), "Content-Type": "application/json"}, content=body)
        self.assertEqual(response.status_code, 422, response.text)
        self.assertIsInstance(response.json()["detail"], list)
        with self.Session() as db:
            self.assertEqual(db.query(Marks).count(), 0)

    def test_database_enforces_mark_identity_score_and_period_constraints(self):
        token = self.teacher_token()
        learner_id = self.learner(token)
        row = mark_payload(learner_id)
        self.assertEqual(self.submit(token, [row]).status_code, 200)
        for changes in ({}, {"term": 4}, {"mathematics": 101, "term": 2}, {"mathematics": None, "term": 2}, {"learner_id": None, "term": 2}):
            with self.Session() as db:
                with self.assertRaises(IntegrityError):
                    db.execute(Marks.__table__.insert().values(**{**row, **changes}, name="Test Learner"))
                    db.commit()
                db.rollback()

    def test_fee_payment_retry_totals_and_history_pagination(self):
        token = self.admin_token()
        fee = self.fee(token, self.learner(token))
        payment = {"category": "school", "amount": 250, "payment_date": "2026-10-25"}
        request_headers = headers(token, "receipt-1")
        url = f"/fees/records/{fee['id']}/payments"
        first = self.client.post(url, headers=request_headers, json=payment)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(self.client.post(url, headers=request_headers, json=payment).json(), first.json())
        self.assertEqual(self.client.post(url, headers=request_headers, json={**payment, "amount": 500}).status_code, 409)
        self.assertEqual(self.client.post(url, headers=headers(token), json={**payment, "amount": 100}).status_code, 200)
        page = self.client.get(url + "?limit=1&offset=1", headers=headers(token)).json()
        self.assertEqual(page["total"], 2)
        self.assertEqual(len(page["items"]), 1)
        self.assertEqual(page["items"][0]["amount"], 100)
        summary = self.client.get("/fees/summary/grade/7", headers=headers(token)).json()
        self.assertEqual(summary["collected"], 350)
        self.assertEqual(summary["balance"], 650)
        for amount in ("Infinity", "NaN", -1, 0):
            self.assertEqual(self.client.post(url, headers=headers(token), json={**payment, "amount": amount}).status_code, 422)
        with self.Session() as db:
            self.assertEqual(db.query(FeePayment).count(), 2)
            self.assertEqual(db.query(AdminActivity).filter_by(action="payment_recorded").count(), 2)

    def test_reports_join_by_id_and_period_and_paginate_without_changing_totals(self):
        token = self.admin_token()
        teacher = self.teacher_token()
        first, second = self.learner(token, "Same Name"), self.learner(token, "Same Name")
        self.fee(token, first)
        self.fee(token, second)
        self.assertEqual(self.submit(teacher, [mark_payload(first, **{field: 90 for field in Scores.model_fields}), mark_payload(second, term=2)]).status_code, 200)
        page = self.client.get("/reports/dashboard?academic_year=2026&term=3&limit=1", headers=headers(token))
        self.assertEqual(page.status_code, 200, page.text)
        body = page.json()
        self.assertEqual(body["total"], 2)
        self.assertEqual(len(body["items"]), 1)
        self.assertEqual(body["school_summary"]["total_required"], 2000)
        self.assertEqual(body["school_summary"]["average_school_score"], 90)
        detail = self.client.get(f"/reports/learner/{second}?academic_year=2026&term=3", headers=headers(token)).json()
        self.assertIsNone(detail["marks"])
        self.assertEqual(detail["learner_id"], second)

    def test_fee_validation_rejects_name_based_and_nonfinite_inputs(self):
        token = self.admin_token()
        learner_id = self.learner(token)
        body = {"learner_id": learner_id, "grade": "7", "academic_year": 2026, "term": 3}
        for invalid in ({**body, "grade": " "}, {**body, "school_required": "Infinity"}, {**body, "school_required": "NaN"}, {**body, "learner_name": "Name based write"}):
            self.assertEqual(self.client.post("/fees", headers=headers(token), json=invalid).status_code, 422)
        with self.Session() as db:
            self.assertEqual(db.query(Fee).count(), 0)

    def test_learner_report_never_combines_different_classes(self):
        admin = self.admin_token()
        teacher = self.teacher_token()
        learner_id = self.learner(admin)
        self.fee(admin, learner_id)  # Class 7 charges
        response = self.submit(teacher, [mark_payload(learner_id, class_name="8")])
        self.assertEqual(response.status_code, 200, response.text)
        path = f"/reports/learner/{learner_id}?academic_year=2026&term=3"
        self.assertEqual(self.client.get(path, headers=headers(admin)).status_code, 409)
        fee_only = self.client.get(path + "&class_name=7", headers=headers(admin)).json()
        mark_only = self.client.get(path + "&class_name=8", headers=headers(admin)).json()
        self.assertIsNone(fee_only["marks"])
        self.assertIsNone(mark_only["fees"])
        self.assertEqual(mark_only["marks"]["class_name"], "8")


if __name__ == "__main__":
    unittest.main()
