"""Initialize the app database and optionally create its first admin account."""
import os

from app.core.passwords import hash_password
from app.core.database import SessionLocal, init_db
from app.models.user import User


init_db()
admin_username = os.getenv("INITIAL_ADMIN_USERNAME")
admin_password = os.getenv("INITIAL_ADMIN_PASSWORD")

if not admin_username and not admin_password:
    print("Database tables initialized. Set INITIAL_ADMIN_USERNAME and INITIAL_ADMIN_PASSWORD to create an admin.")
elif not admin_username or not admin_password:
    raise SystemExit("Set both INITIAL_ADMIN_USERNAME and INITIAL_ADMIN_PASSWORD.")
else:
    if len(admin_password) < 12:
        raise SystemExit("Administrator password must contain at least 12 characters")
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.username == admin_username).first()
        if existing:
            if existing.role != "admin":
                raise SystemExit("Existing account is not an administrator")
            print("Administrator account already exists; no password was changed.")
        else:
            db.add(User(
                username=admin_username,
                hashed_password=hash_password(admin_password),
                role="admin",
            ))
            db.commit()
            print("Administrator account created.")
    finally:
        db.close()
