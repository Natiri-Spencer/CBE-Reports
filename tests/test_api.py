import json
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models.marks import Marks
from app.models.user import User

FIXTURES = Path(__file__).parent / "fixtures"


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.Session = sessionmaker(bind=cls.engine, autocommit=False, autoflush=False)
        Base.metadata.create_all(bind=cls.engine)

        def test_db():
            db = cls.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = test_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        cls.engine.dispose()

    def setUp(self):
        db = self.Session()
        try:
            db.query(Marks).delete()
            db.query(User).delete()
            db.commit()
        finally:
            db.close()

    def teacher_token(self):
        signup = self.client.post(
            "/auth/signup",
            json={"username": "teacher1", "password": "testing-password", "role": "teacher"},
        )
        self.assertEqual(signup.status_code, 200, signup.text)
        login = self.client.post(
            "/auth/token",
            data={"username": "teacher1", "password": "testing-password"},
        )
        self.assertEqual(login.status_code, 200, login.text)
        return login.json()["access_token"]

    def test_health(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_teacher_can_submit_complete_marks(self):
        token = self.teacher_token()
        response = self.client.post(
            "/marks/submit",
            headers={"Authorization": f"Bearer {token}"},
            json=json.loads((FIXTURES / "marks_submission.json").read_text(encoding="utf-8")),
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["results"][0]["name"], "Amina Test")

    def test_teacher_cannot_open_admin_dashboard(self):
        token = self.teacher_token()
        response = self.client.get(
            "/admin/dashboard",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(response.status_code, 403)

    def test_marks_require_authentication(self):
        response = self.client.get("/marks")
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
