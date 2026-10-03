import base64
import hashlib
import json
from typing import Any

from cryptography.fernet import Fernet

from app.core.config import Settings, get_settings
from app.security.tokens import hash_fingerprint


def encrypt_json(value: dict[str, Any], settings: Settings | None = None) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _fernet(settings).encrypt(payload).decode("utf-8")


def decrypt_json(token: str, settings: Settings | None = None) -> dict[str, Any]:
    raw = _fernet(settings).decrypt(token.encode("utf-8")).decode("utf-8")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Credential payload must decrypt to an object")
    return value


def fingerprint_material(value: dict[str, Any], settings: Settings | None = None) -> str:
    active_settings = settings or get_settings()
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    fingerprint = hash_fingerprint(canonical, active_settings.session_secret)
    if fingerprint is None:
        raise ValueError("Credential fingerprint cannot be empty")
    return fingerprint


def _fernet(settings: Settings | None = None) -> Fernet:
    active_settings = settings or get_settings()
    key = active_settings.credential_encryption_key
    if not key:
        if active_settings.app_env == "production":
            raise RuntimeError("AIMAGICIAN_CREDENTIAL_ENCRYPTION_KEY is required in production")
        key = active_settings.session_secret
    return Fernet(_normalize_fernet_key(key))


def _normalize_fernet_key(raw_key: str) -> bytes:
    candidate = raw_key.encode("utf-8")
    try:
        Fernet(candidate)
        return candidate
    except ValueError:
        digest = hashlib.sha256(candidate).digest()
        return base64.urlsafe_b64encode(digest)
