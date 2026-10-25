"""Initialize the app database and optionally create its first admin account."""
import os

from app.core.auth import pwd_context
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
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.username == admin_username).first()
        if existing:
            print(f"Admin account '{admin_username}' already exists; no password was changed.")
        else:
            db.add(User(
                username=admin_username,
                hashed_password=pwd_context.hash(admin_password),
                role="admin",
            ))
            db.commit()
            print(f"Admin account '{admin_username}' created.")
    finally:
        db.close()
