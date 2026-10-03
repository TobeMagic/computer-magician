import re
from collections.abc import Mapping, Sequence
from typing import Any


SENSITIVE_KEY_PARTS = ("password", "token", "secret", "cookie", "authorization", "api_key", "apikey")
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"ghp_[A-Za-z0-9]{12,}"),
    re.compile(r"\b1[3-9]\d{9}\b"),
    re.compile(r"(?<![\w-])\d{6}(?![\w-])"),
)


def redact_value(value: Any) -> Any:
    if isinstance(value, str):
        redacted = value.replace("\x00", "")
        for pattern in SECRET_PATTERNS:
            redacted = pattern.sub("[REDACTED]", redacted)
        return redacted
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if _is_sensitive_key(str(key)) else redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [redact_value(item) for item in value]
    return value


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)
