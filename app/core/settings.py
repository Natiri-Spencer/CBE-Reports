"""Validated configuration shared by the server and operational commands."""
import os
from pathlib import Path
from urllib.parse import urlsplit
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(os.getenv("APP_ENV_FILE", str(ROOT / ".env")), override=False)
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "")
if (len(SECRET_KEY.encode()) < 32 or len(set(SECRET_KEY)) < 12
        or any(word in SECRET_KEY.lower() for word in ("replace", "change", "development", "default", "example", "secret"))):
    raise RuntimeError("Configure JWT_SECRET_KEY with a unique randomly generated secret of at least 32 bytes")

ACCESS_SECONDS = 15 * 60
SESSION_SECONDS = 7 * 24 * 60 * 60
ISSUER = "grade-school-api"
AUDIENCE = "grade-school-client"
CORS_ORIGINS = [s.strip() for s in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000,https://localhost").split(",") if s.strip()]
for origin in CORS_ORIGINS:
    parsed = urlsplit(origin)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username
            or parsed.password or parsed.path or parsed.query or parsed.fragment or "*" in origin):
        raise RuntimeError("CORS_ORIGINS must contain exact http(s) origins without paths or wildcards")
