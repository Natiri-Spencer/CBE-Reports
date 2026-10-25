import os as _os
import secrets as _secrets
_os.environ.setdefault("JWT_SECRET_KEY", _secrets.token_urlsafe(48))
"""Serve an isolated synthetic school for manual browser verification only."""
import os
from pathlib import Path
import sys
from tempfile import mkdtemp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
(ROOT / ".local").mkdir(exist_ok=True)
DIRECTORY = Path(mkdtemp(prefix="browser-fixture-", dir=ROOT / ".local"))
os.environ.update(DATABASE_URL="sqlite:///" + (DIRECTORY / "school.sqlite3").as_posix(),
                  ENV="DEV", JWT_SECRET_KEY=_secrets.token_urlsafe(48),
                  BACKUP_DIRECTORY=str(DIRECTORY / "backups"), CORS_ORIGINS="http://127.0.0.1:3001,http://localhost:3001")

from app.core.database import init_db, SessionLocal
from app.core.passwords import hash_password
from app.main import app
from app.models.user import User
from app.models.learner import Learner
from app.models.fee import Fee

init_db()
with SessionLocal() as db:
    db.add_all([User(username="test_teacher", role="teacher", hashed_password=hash_password("synthetic-test-password")),
                User(username="test_admin", role="admin", hashed_password=hash_password("synthetic-test-password"))])
    learners = [Learner(name="Same Name", class_name="7"), Learner(name="Same Name", class_name="7")]
    learners += [Learner(name=f"Synthetic Learner {index:03d}", class_name="7") for index in range(51)]
    db.add_all(learners)
    db.flush()
    db.add(Fee(learner_id=learners[0].id, learner_name=learners[0].name, grade="7", academic_year=2026, term=3,
               school_required=1000, total_required=1000, total_paid=0, total_balance=1000))
    db.commit()

if __name__ == "__main__":
    import uvicorn
    print("Synthetic browser fixture only; real school database is not in use.")
    print(f"Fixture directory: {DIRECTORY}")
    uvicorn.run(app, host="127.0.0.1", port=8765, access_log=False, proxy_headers=False)
