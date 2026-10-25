"""Generate local secrets without displaying them or overwriting existing configuration."""
from pathlib import Path
import secrets
from cryptography.fernet import Fernet
root = Path(__file__).resolve().parents[1]
path = root / ".env"
if path.exists():
    raise SystemExit("Configuration already exists; no secrets were changed")
path.write_text("JWT_SECRET_KEY=" + secrets.token_urlsafe(48) + "\nBACKUP_ENCRYPTION_KEY=" + Fernet.generate_key().decode() + "\nCORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,https://localhost\n", encoding="utf-8")
print("Local configuration created. Protect this file and keep a separate secure copy of the backup key.")
