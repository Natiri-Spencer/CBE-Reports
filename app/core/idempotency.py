"""Persist responses in the same transaction as the mutations they describe."""
from hashlib import sha256
import json
from typing import Annotated

from fastapi import Header, HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.models.request_receipt import RequestReceipt

IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]


def execute_once(db: Session, actor_id: int, operation: str, key: str, payload, action):
    fingerprint = sha256(json.dumps(jsonable_encoder(payload), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    connection = None
    try:
        connection = db.connection()
        if connection.dialect.name == "sqlite":
            # Auth has already performed a SELECT on this session. Acquire the
            # write lock before reading receipts, balances, or existing marks.
            if not connection.connection.driver_connection.in_transaction:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
        receipt = db.query(RequestReceipt).filter_by(actor_id=actor_id, operation=operation, key=key).first()
        if receipt:
            if receipt.request_hash != fingerprint:
                raise HTTPException(status_code=409, detail="Idempotency key was already used for a different request")
            response = receipt.response_body
            db.rollback()  # release the write lock; a replay changes nothing
            return response
        response = jsonable_encoder(action())
        db.add(RequestReceipt(actor_id=actor_id, operation=operation, key=key,
                              request_hash=fingerprint, response_body=response))
        db.commit()
        return response
    except OperationalError as exc:
        db.rollback()
        if db.get_bind().dialect.name == "sqlite" and ("locked" in str(exc).lower() or "busy" in str(exc).lower()):
            raise HTTPException(status_code=503, detail="Database is busy; retry with the same Idempotency-Key", headers={"Retry-After": "1"}) from exc
        raise
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="The operation conflicts with an existing record") from exc
    except Exception:
        db.rollback()
        raise
