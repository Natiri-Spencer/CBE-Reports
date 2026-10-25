"""Application-owned daily backup scheduling, independent of interactive logins."""
import asyncio
from contextlib import asynccontextmanager, suppress
import json
import logging
import time
from app.core.backups import BACKUP_DIRECTORY, backup, backup_is_current

async def maintain_backups():
    while True:
        try:
            latest = json.loads((BACKUP_DIRECTORY / "latest.json").read_text()) if backup_is_current() else {}
            if time.time() - latest.get("created_at", 0) >= 24 * 3600:
                await asyncio.to_thread(backup)
                logging.getLogger("school.security").info("backup_restore_verified")
        except Exception:
            logging.getLogger("school.security").error("backup_failed")
        await asyncio.sleep(30 * 60)

@asynccontextmanager
async def lifespan(app):
    worker = asyncio.create_task(maintain_backups(), name="daily-verified-backup")
    try:
        yield
    finally:
        worker.cancel()
        with suppress(asyncio.CancelledError):
            await worker
