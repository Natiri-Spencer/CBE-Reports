"""The only password hashing implementation used by the application."""
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError

hasher = PasswordHasher()
_dummy = hasher.hash("unusable-dummy-password")

def hash_password(password: str) -> str:
    return hasher.hash(password)

def verify_password(password: str, encoded: str | None) -> bool:
    try:
        valid = hasher.verify(encoded or _dummy, password)
        return bool(encoded) and valid
    except (VerificationError, InvalidHashError):
        return False
