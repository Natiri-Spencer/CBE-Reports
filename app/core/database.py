# app/core/database.py
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
from pathlib import Path
import os
from app.core import settings  # load and validate environment before opening the database

DATABASE_PATH = Path(__file__).resolve().parents[2] / "fees.db"
SQLALCHEMY_DATABASE_URL = os.getenv(
    "DATABASE_URL", f"sqlite:///{DATABASE_PATH.as_posix()}"
)

engine_options = {}
if SQLALCHEMY_DATABASE_URL.startswith("sqlite"):
    engine_options["connect_args"] = {"check_same_thread": False, "timeout": 30}

engine = create_engine(SQLALCHEMY_DATABASE_URL, hide_parameters=True, **engine_options)
if engine.dialect.name == "sqlite":
    @event.listens_for(engine, "connect")
    def enforce_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# Schema changes are explicit Alembic migrations, never application-import work.
def init_db(db_engine=engine):
    from alembic import command
    from alembic.config import Config

    configuration = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    with db_engine.begin() as connection:
        configuration.attributes["connection"] = connection
        command.upgrade(configuration, "head")

# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
