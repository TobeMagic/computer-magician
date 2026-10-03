import hashlib
import hmac
import secrets


def generate_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_token(token: str, expected_hash: str, secret: str) -> bool:
    if not token or not expected_hash:
        return False
    return hmac.compare_digest(hash_token(token, secret), expected_hash)


def hash_fingerprint(value: str | None, secret: str) -> str | None:
    if not value:
        return None
    return hash_token(value, secret)
