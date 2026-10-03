from fastapi.testclient import TestClient


def test_admin_redirects_to_login_when_unauthenticated(client: TestClient) -> None:
    response = client.get("/admin", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/admin/login?next=")


def test_admin_login_page_is_browser_login(client: TestClient) -> None:
    response = client.get("/admin/login")

    assert response.status_code == 200
    assert "Admin Login" in response.text
    assert "/api/auth/login" in response.text
    assert "cdn.tailwindcss.com" in response.text
    assert "Apple-style glass console" in response.text


def test_admin_page_loads_after_api_login(authenticated_client: tuple[TestClient, str]) -> None:
    client, _ = authenticated_client

    response = client.get("/admin")

    assert response.status_code == 200
    assert "AImagician Control Ledger" in response.text
    assert "cdn.tailwindcss.com" in response.text
    assert "Apple-style glass console" in response.text


def test_admin_notion_import_page_loads_after_api_login(authenticated_client: tuple[TestClient, str]) -> None:
    client, _ = authenticated_client

    response = client.get("/admin/notion-import")

    assert response.status_code == 200
    assert "Notion Import Control" in response.text
    assert "/api/notion-import/summary" in response.text
    assert "/api/notion-sync/outbox/drain" in response.text


def test_admin_spa_page_loads_after_api_login(authenticated_client: tuple[TestClient, str]) -> None:
    client, _ = authenticated_client

    response = client.get("/admin/spa")

    assert response.status_code == 200
    assert "AImagician SPA Console" in response.text
    assert "Operations SPA" in response.text
    assert "/api/prompts/import-source-files" in response.text
    assert "/api/notion-import/summary" in response.text
    assert "/api/platforms" in response.text
    assert "routeTo('logs')" in response.text
