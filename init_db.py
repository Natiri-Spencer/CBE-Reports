# init_db.py
from app.database import Base, engine, SessionLocal
from app.models.user import User
from app.core.auth import pwd_context

# Create tables
Base.metadata.create_all(bind=engine)

# Seed users
db = SessionLocal()
admin = User(
    username="admin",
    hashed_password=pwd_context.hash("admin123"),
    role="admin"
)
teacher = User(
    username="teacher",
    hashed_password=pwd_context.hash("teacher123"),
    role="teacher"
)

db.add(admin)
db.add(teacher)
db.commit()
db.close()

print("✅ Database initialized with admin and teacher accounts")
