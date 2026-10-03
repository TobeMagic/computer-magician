from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError, VerificationError
from argon2.low_level import Type


_PASSWORD_HASHER = PasswordHasher(type=Type.ID)


def hash_password(raw_password: str) -> str:
    if not raw_password:
        raise ValueError("password must not be empty")
    return _PASSWORD_HASHER.hash(raw_password)


def verify_password(raw_password: str, password_hash: str) -> bool:
    if not raw_password or not password_hash:
        return False
    try:
        return _PASSWORD_HASHER.verify(password_hash, raw_password)
    except (InvalidHashError, VerifyMismatchError, VerificationError):
        return False
