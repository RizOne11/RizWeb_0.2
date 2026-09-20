import base64

import app as puma_app


def _basic(user: str, password: str) -> dict[str, str]:
    raw = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {raw}"}


def _clear_auth(monkeypatch):
    monkeypatch.delenv("PUMA_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("PUMA_AUTH_USER", raising=False)
    monkeypatch.delenv("PUMA_REQUIRE_AUTH", raising=False)


def test_auth_is_backward_compatible_when_not_configured(monkeypatch):
    _clear_auth(monkeypatch)
    client = puma_app.app.test_client()
    response = client.get("/")
    assert response.status_code == 200


def test_bearer_token_allows_browser_and_api_routes(monkeypatch):
    _clear_auth(monkeypatch)
    monkeypatch.setenv("PUMA_AUTH_TOKEN", "secret-token")
    client = puma_app.app.test_client()

    response = client.get("/", headers={"Authorization": "Bearer secret-token"})
    assert response.status_code == 200

    response = client.get(
        "/api/jobs/does-not-exist",
        headers={"Authorization": "Bearer secret-token"},
    )
    assert response.status_code == 404


def test_basic_auth_supports_browser_prompt(monkeypatch):
    _clear_auth(monkeypatch)
    monkeypatch.setenv("PUMA_AUTH_TOKEN", "secret-token")
    monkeypatch.setenv("PUMA_AUTH_USER", "puma-admin")
    client = puma_app.app.test_client()

    response = client.get("/", headers=_basic("puma-admin", "secret-token"))
    assert response.status_code == 200


def test_missing_or_wrong_token_is_rejected(monkeypatch):
    _clear_auth(monkeypatch)
    monkeypatch.setenv("PUMA_AUTH_TOKEN", "secret-token")
    client = puma_app.app.test_client()

    response = client.get("/")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"].startswith("Basic ")

    response = client.get(
        "/api/jobs/does-not-exist",
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert response.status_code == 401
    assert response.get_json()["error"] == "authentication_required"


def test_x_puma_token_header_is_supported_for_automation(monkeypatch):
    _clear_auth(monkeypatch)
    monkeypatch.setenv("PUMA_AUTH_TOKEN", "secret-token")
    client = puma_app.app.test_client()

    response = client.get("/", headers={"X-PUMA-Token": "secret-token"})
    assert response.status_code == 200


def test_required_auth_without_secret_fails_closed(monkeypatch):
    _clear_auth(monkeypatch)
    monkeypatch.setenv("PUMA_REQUIRE_AUTH", "1")
    client = puma_app.app.test_client()

    response = client.get("/")
    assert response.status_code == 503

    response = client.get("/api/jobs/does-not-exist")
    assert response.status_code == 503
    assert response.get_json()["error"] == "auth_not_configured"


def test_healthz_remains_public_when_auth_is_required(monkeypatch):
    _clear_auth(monkeypatch)
    monkeypatch.setenv("PUMA_AUTH_TOKEN", "secret-token")
    monkeypatch.setenv("PUMA_REQUIRE_AUTH", "1")
    client = puma_app.app.test_client()

    response = client.get("/healthz")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["service"] == "puma"
