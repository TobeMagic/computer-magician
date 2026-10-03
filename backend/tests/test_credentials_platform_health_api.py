from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.models.audit_event import AuditEvent
from app.models.credentials import CredentialMaterial, PlatformHealth
from app.models.runtime import EventLog, Job
from app.security.credentials import decrypt_json
from app.security.tokens import hash_token
from app.services.platform_native import _normalize_browser_login_method, run_platform_health_check_job, run_platform_login_job


def csrf_headers(csrf_token: str) -> dict[str, str]:
    return {"X-CSRF-Token": csrf_token}


def configure_upload_token(monkeypatch, token: str = "credential-upload-token") -> str:
    settings = get_settings()
    monkeypatch.setenv(
        "AIMAGICIAN_CREDENTIAL_UPLOAD_TOKEN_HASH",
        hash_token(token, settings.session_secret),
    )
    get_settings.cache_clear()
    return token


def test_browser_login_method_normalizes_api_default_to_runner_sms() -> None:
    assert _normalize_browser_login_method("browser_sms", action="bootstrap") == "sms"
    assert _normalize_browser_login_method("phone-sms", action="request_code") == "sms"
    assert _normalize_browser_login_method("", action="submit_code") == "sms"
    assert _normalize_browser_login_method("browser_password", action="bootstrap") == "password"


def test_credential_upload_requires_remote_token(client) -> None:
    response = client.post(
        "/api/credentials/知乎/upload",
        json={"credential_kind": "browser_session", "material": {"cookie": "secret-cookie"}},
    )

    assert response.status_code == 403


def test_credential_upload_encrypts_and_only_returns_metadata(
    client,
    db_session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    token = configure_upload_token(monkeypatch)
    response = client.post(
        "/api/credentials/知乎/upload",
        headers={"X-AImagician-Upload-Token": token},
        json={
            "credential_kind": "browser_session",
            "material": {"cookie": "secret-cookie-value", "localStorage": {"token": "secret-token-value"}},
            "source_machine": "gui-runner-01",
            "notes": "use browser-exported session",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "stored"
    assert body["credential"]["platform"] == "知乎"
    assert body["credential"]["source_machine"] == "gui-runner-01"
    assert "encrypted_blob" not in body["credential"]
    assert "material" not in body["credential"]
    assert body["health"]["readiness"] == "validation_pending"
    assert body["next_action"] == "POST /api/platforms/知乎/check-session"

    with db_session_factory() as db:
        stored = db.execute(select(CredentialMaterial)).scalar_one()
        assert stored.platform == "知乎"
        assert stored.fingerprint
        assert "secret-cookie-value" not in stored.encrypted_blob
        assert "secret-token-value" not in stored.encrypted_blob
        health = db.execute(select(PlatformHealth).where(PlatformHealth.platform == "知乎")).scalar_one()
        assert health.credential_id == UUID(body["credential"]["id"])
        assert db.execute(select(AuditEvent).where(AuditEvent.event_type == "credential.stored")).scalar_one()
        event = db.execute(select(EventLog).where(EventLog.event_type == "platform.credential_uploaded")).scalar_one()
        assert "secret-cookie-value" not in str(event.payload_json)


def test_platform_credentials_return_metadata_and_never_return_secrets(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    client, csrf_token = authenticated_client
    token = configure_upload_token(monkeypatch)
    upload = client.post(
        "/api/credentials/InfoQ/upload",
        headers={"X-AImagician-Upload-Token": token},
        json={"credential_kind": "browser_session", "material": {"cookie": "infoq-secret-cookie"}},
    )
    assert upload.status_code == 201

    listing = client.get("/api/platforms/InfoQ/credentials")
    assert listing.status_code == 200
    assert len(listing.json()) == 1
    assert "infoq-secret-cookie" not in str(listing.json())
    assert "encrypted_blob" not in listing.json()[0]

    health = client.get("/api/platforms/InfoQ/health")
    assert health.status_code == 200
    assert health.json()["readiness"] == "validation_pending"

    # Keep the CSRF token live for the following mutation path.
    assert csrf_token

    with db_session_factory() as db:
        assert db.execute(select(CredentialMaterial).where(CredentialMaterial.platform == "InfoQ")).scalar_one()


def test_platform_health_check_enqueues_idempotent_job(authenticated_client) -> None:
    client, csrf_token = authenticated_client
    response = client.post(
        "/api/platforms/知乎/check-session",
        headers=csrf_headers(csrf_token),
        json={
            "idempotency_key": "zhihu-check-session",
            "input_json": {"mode": "headless_check"},
            "timeout_seconds": 120,
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body["health"]["platform"] == "知乎"
    assert body["health"]["status"] == "checking"
    assert body["health"]["readiness"] == "check_queued"
    assert body["run"]["run_type"] == "platform_health_check"
    assert body["job"]["job_type"] == "platform_health_check"
    assert body["job"]["input_json"]["platform"] == "知乎"
    assert body["job"]["input_json"]["input"]["mode"] == "headless_check"

    repeated = client.post(
        "/api/platforms/知乎/check-session",
        headers=csrf_headers(csrf_token),
        json={"idempotency_key": "zhihu-check-session", "timeout_seconds": 120},
    )
    assert repeated.status_code == 202
    assert repeated.json()["run"]["id"] == body["run"]["id"]
    assert repeated.json()["job"]["id"] == body["job"]["id"]


def test_platform_login_code_api_enqueues_request_and_submit(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    client, csrf_token = authenticated_client

    request_code = client.post(
        "/api/platforms/InfoQ/login/request-code",
        headers=csrf_headers(csrf_token),
        json={
            "phone": "13431877826",
            "idempotency_key": "infoq-login-code-request",
            "input_json": {"mode": "sms"},
        },
    )

    assert request_code.status_code == 202
    request_body = request_code.json()
    assert request_body["health"]["platform"] == "InfoQ"
    assert request_body["health"]["readiness"] == "login_code_requested"
    assert request_body["job"]["job_type"] == "platform_login_request_code"
    assert request_body["job"]["input_json"]["phone_masked"] == "134****7826"
    assert "13431877826" not in str(request_body)

    submit_code = client.post(
        "/api/platforms/InfoQ/login/submit-code",
        headers=csrf_headers(csrf_token),
        json={
            "code": "156116",
            "idempotency_key": "infoq-login-code-submit",
            "input_json": {"mode": "sms"},
        },
    )

    assert submit_code.status_code == 202
    submit_body = submit_code.json()
    assert submit_body["health"]["readiness"] == "login_code_submitted"
    assert submit_body["job"]["job_type"] == "platform_login_submit_code"
    assert submit_body["job"]["input_json"]["code_masked"] == "******"
    assert "156116" not in str(submit_body)

    with db_session_factory() as db:
        job = db.get(Job, UUID(submit_body["job"]["id"]))
        assert job is not None
        assert "156116" not in str(job.input_json)
        material = db.get(CredentialMaterial, UUID(job.metadata_json["credential_material_id"]))
        assert material is not None
        assert material.credential_kind == "login_sms_submit"
        assert "156116" not in material.encrypted_blob
        assert decrypt_json(material.encrypted_blob)["code"] == "156116"

        captured: dict[str, object] = {}

        class FakeResponse:
            status_code = 200
            text = '{"status":"ok"}'

            def json(self) -> dict[str, str]:
                return {"status": "ok"}

        def fake_post(url: str, json: dict, timeout: float) -> FakeResponse:
            captured["url"] = url
            captured["json"] = json
            captured["timeout"] = timeout
            return FakeResponse()

        monkeypatch.setenv("AIMAGICIAN_NATIVE_LOGIN_INFOQ_SUBMIT_CODE_URL", "http://gui-runner.local/infoq/submit")
        monkeypatch.setattr("app.services.platform_native.requests.post", fake_post)

        result = run_platform_login_job(job)

    assert result["status"] == "ok"
    assert captured["url"] == "http://gui-runner.local/infoq/submit"
    assert captured["json"]["secret_input"]["code"] == "156116"
    assert "156116" not in str(result)


def test_infoq_login_without_endpoint_uses_publisher_worker_not_legacy_script(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.delenv("AIMAGICIAN_NATIVE_LOGIN_INFOQ_REQUEST_CODE_URL", raising=False)
    monkeypatch.setenv("AIMAGICIAN_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    get_settings.cache_clear()

    def fake_wait(db, *, worker_job, timeout_seconds, poll_interval_seconds=2.0):
        del db, timeout_seconds, poll_interval_seconds
        artifact = worker_job.artifact_json
        assert artifact["phone_number"] != "13431877826"
        assert Path(artifact["phone_number_file"]).read_text(encoding="utf-8") == "13431877826"
        return {"status": "blocked", "reason": "sms_code_required", "final_blocker": "sms_code_required"}

    monkeypatch.setattr(
        "app.services.platform_native.wait_for_publisher_worker_job",
        fake_wait,
    )
    client, csrf_token = authenticated_client

    response = client.post(
        "/api/platforms/InfoQ/login/request-code",
        headers=csrf_headers(csrf_token),
        json={"phone": "13431877826", "idempotency_key": "infoq-login-no-endpoint"},
    )
    assert response.status_code == 202

    with db_session_factory() as db:
        job = db.get(Job, UUID(response.json()["job"]["id"]))
        assert job is not None
        result = run_platform_login_job(job)

    assert result["status"] == "login_waiting_for_sms"
    assert result["execution_mode"] == "native_backend"
    assert result["publisher_worker"]["action"] == "bootstrap-session"
    assert "native_script_bridge" not in str(result)
    assert "publish_infoq_push.py" not in str(result)


def test_infoq_health_without_endpoint_uses_cached_credential_path_not_script(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    monkeypatch.delenv("AIMAGICIAN_NATIVE_HEALTH_INFOQ_URL", raising=False)
    monkeypatch.setattr(
        "app.services.platform_native.wait_for_publisher_worker_job",
        lambda *args, **kwargs: {"status": "ok", "live_ready": True, "reason": "editor_surface_reached"},
    )
    client, csrf_token = authenticated_client

    response = client.post(
        "/api/platforms/InfoQ/check-session",
        headers=csrf_headers(csrf_token),
        json={"idempotency_key": "infoq-health-no-endpoint", "timeout_seconds": 30},
    )
    assert response.status_code == 202

    with db_session_factory() as db:
        job = db.get(Job, UUID(response.json()["job"]["id"]))
        assert job is not None
        result = run_platform_health_check_job(job)

    assert result["status"] == "session_ready"
    assert result["execution_mode"] == "native_backend"
    assert result["publisher_worker"]["action"] == "check-session"
    assert "native_script_bridge" not in str(result)
    assert "publish_infoq_push.py" not in str(result)


def test_platform_login_bootstrap_api_enqueues_gui_runner_job(
    authenticated_client,
    db_session_factory: sessionmaker[Session],
    monkeypatch,
) -> None:
    client, csrf_token = authenticated_client

    response = client.post(
        "/api/platforms/知乎/login/bootstrap",
        headers=csrf_headers(csrf_token),
        json={
            "login_method": "browser_sms",
            "idempotency_key": "zhihu-bootstrap",
            "input_json": {"mode": "visible_browser"},
            "timeout_seconds": 900,
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body["health"]["readiness"] == "login_bootstrap_queued"
    assert body["job"]["job_type"] == "platform_login_bootstrap"
    assert body["job"]["input_json"]["platform"] == "知乎"
    assert body["job"]["input_json"]["login_method"] == "browser_sms"

    with db_session_factory() as db:
        job = db.get(Job, UUID(body["job"]["id"]))
        assert job is not None

        captured: dict[str, object] = {}

        class FakeResponse:
            status_code = 200
            text = '{"status":"waiting_for_human","next_action":"scan qr or request sms"}'

            def json(self) -> dict[str, str]:
                return {"status": "waiting_for_human", "next_action": "scan qr or request sms"}

        def fake_post(url: str, json: dict, timeout: float) -> FakeResponse:
            captured["url"] = url
            captured["json"] = json
            captured["timeout"] = timeout
            return FakeResponse()

        monkeypatch.setenv("AIMAGICIAN_NATIVE_LOGIN_ZHIHU_BOOTSTRAP_URL", "http://gui-runner.local/zhihu/bootstrap")
        monkeypatch.setattr("app.services.platform_native.requests.post", fake_post)

        result = run_platform_login_job(job)

    assert result["status"] == "waiting_for_human"
    assert captured["url"] == "http://gui-runner.local/zhihu/bootstrap"
    assert captured["json"]["login_method"] == "browser_sms"


def test_platform_operations_admin_pages_load(authenticated_client, monkeypatch) -> None:
    client, csrf_token = authenticated_client
    token = configure_upload_token(monkeypatch)
    upload = client.post(
        "/api/credentials/InfoQ/upload",
        headers={"X-AImagician-Upload-Token": token},
        json={
            "credential_kind": "browser_session",
            "material": {"cookie": "infoq-secret-cookie"},
            "source_machine": "gui-runner-01",
        },
    )
    assert upload.status_code == 201

    platforms = client.get("/admin/platforms")
    detail = client.get("/admin/platforms/InfoQ")

    assert platforms.status_code == 200
    assert "Platform Operations" in platforms.text
    assert "Platform Readiness" in platforms.text
    assert detail.status_code == 200
    assert "Platform Session Console" in detail.text
    assert "GUI Runner Login" in detail.text
    assert "/login/bootstrap" in detail.text
    assert "/login/request-code" in detail.text
    assert "/login/submit-code" in detail.text
    assert "Credential Upload Command" in detail.text
    assert "X-AImagician-Upload-Token" in detail.text
    assert "infoq-secret-cookie" not in detail.text

    check = client.post(
        "/api/platforms/InfoQ/check-session",
        headers=csrf_headers(csrf_token),
        json={"idempotency_key": "infoq-admin-page-check", "timeout_seconds": 120},
    )
    assert check.status_code == 202
