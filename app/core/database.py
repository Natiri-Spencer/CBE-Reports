# app/core/database.py
from sqlalchemy import create_engine
from sqlalchemy import inspect, text
from sqlalchemy.orm import sessionmaker, declarative_base
from pathlib import Path
import os

DATABASE_PATH = Path(__file__).resolve().parents[2] / "fees.db"
SQLALCHEMY_DATABASE_URL = os.getenv(
    "DATABASE_URL", f"sqlite:///{DATABASE_PATH.as_posix()}"
)

engine_options = {}
if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
    engine_options["connect_args"] = {"check_same_thread": False}

engine = create_engine(SQLALCHEMY_DATABASE_URL, **engine_options)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# Create tables for all models that inherit from Base
def init_db(db_engine=engine):
    import app.models.user
    import app.models.fee
    import app.models.marks
    import app.models.admin_activity
    Base.metadata.create_all(bind=db_engine)

    # Add period columns to existing SQLite fee tables without discarding rows.
    with db_engine.begin() as connection:
        fee_columns = {column["name"] for column in inspect(connection).get_columns("fees")}
        if "academic_year" not in fee_columns:
            connection.execute(text("ALTER TABLE fees ADD COLUMN academic_year INTEGER NOT NULL DEFAULT 0"))
        if "term" not in fee_columns:
            connection.execute(text("ALTER TABLE fees ADD COLUMN term INTEGER NOT NULL DEFAULT 0"))

    # Preserve the paid totals already stored on fee rows as opening balances.
    from app.models.fee import Fee, FeePayment

    local_session = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    db = local_session()
    try:
        categories = ("pta", "remedials", "welfare", "lunch", "school")
        for fee in db.query(Fee).all():
            for category in categories:
                amount = float(getattr(fee, f"{category}_fee") or 0.0)
                if amount <= 0:
                    continue
                exists = db.query(FeePayment.id).filter(
                    FeePayment.fee_id == fee.id,
                    FeePayment.category == category,
                ).first()
                if not exists:
                    db.add(FeePayment(
                        fee_id=fee.id,
                        payment_date=None,
                        category=category,
                        amount=amount,
                        note="Migrated balance; original payment date unavailable.",
                        is_opening_balance=True,
                    ))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
