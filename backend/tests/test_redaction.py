from app.security.redaction import redact_value


def test_redaction_keeps_uuid_but_redacts_standalone_sms_code() -> None:
    value = {
        "version_id": "b2e0b5b7-d4a1-4337-91cc-236155a8aa03",
        "message": "code 753517",
    }

    redacted = redact_value(value)

    assert redacted["version_id"] == value["version_id"]
    assert redacted["message"] == "code [REDACTED]"


def test_redaction_strips_null_bytes_before_jsonb_write() -> None:
    redacted = redact_value({"notes": "ok\x00secret 753517", "nested": ["a\x00b"]})

    assert "\x00" not in redacted["notes"]
    assert redacted["notes"] == "oksecret [REDACTED]"
    assert redacted["nested"] == ["ab"]
