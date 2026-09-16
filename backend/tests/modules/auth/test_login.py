ADMIN_EMAIL = "admin@gmail.com"
ADMIN_PASSWORD = "123456"


async def _login(client, email=ADMIN_EMAIL, password=ADMIN_PASSWORD):
    return await client.post("/api/v1/auth/login", json={"email": email, "password": password})


async def test_login_success_and_me(client):
    response = await _login(client)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["user"]["email"] == ADMIN_EMAIL
    assert data["user"]["role"] == "Administrator"
    assert "ALL_PAGES" in data["user"]["permissions"]

    headers = {"Authorization": f"Bearer {data['access_token']}"}
    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["data"]["email"] == ADMIN_EMAIL


async def test_access_token_lasts_24_hours(client):
    """Users stay signed in for a full day without re-authenticating."""
    from app.core.security import decode_token

    response = await _login(client)
    assert response.status_code == 200
    data = response.json()["data"]

    payload = decode_token(data["access_token"], expected_type="access")
    lifetime_seconds = int(payload["exp"]) - int(payload["iat"])
    assert lifetime_seconds >= 24 * 3600 - 60
    # The SPA receives the matching expires_in (seconds).
    assert abs(int(data["expires_in"]) - lifetime_seconds) <= 1


async def test_login_failure_and_logout_revocation(client):
    response = await _login(client, password="wrong-password")
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "AUTH_REQUIRED"

    response = await _login(client)
    data = response.json()["data"]
    headers = {"Authorization": f"Bearer {data['access_token']}"}

    logout = await client.post("/api/v1/auth/logout", json={"refresh_token": data["refresh_token"]}, headers=headers)
    assert logout.status_code == 200

    refresh = await client.post("/api/v1/auth/refresh", json={"refresh_token": data["refresh_token"]})
    assert refresh.status_code == 401


async def test_refresh_rotation(client):
    response = await _login(client)
    data = response.json()["data"]

    refresh = await client.post("/api/v1/auth/refresh", json={"refresh_token": data["refresh_token"]})
    assert refresh.status_code == 200
    rotated = refresh.json()["data"]
    assert rotated["refresh_token"] != data["refresh_token"]

    replay = await client.post("/api/v1/auth/refresh", json={"refresh_token": data["refresh_token"]})
    assert replay.status_code == 401


async def test_me_requires_auth(client):
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401

    response = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage"})
    assert response.status_code == 401


async def test_refresh_accepts_camel_case_spa_body(client):
    """The SPA token layer posts { refreshToken } — the schema must accept it."""
    response = await _login(client)
    data = response.json()["data"]

    refresh = await client.post("/api/v1/auth/refresh", json={"refreshToken": data["refresh_token"]})
    assert refresh.status_code == 200, refresh.text
    rotated = refresh.json()["data"]
    assert rotated["accessToken"]
    assert rotated["refreshToken"] != data["refresh_token"]


async def test_logout_revokes_camel_case_refresh_token(client):
    """Logout must revoke the refresh JTI even when the body uses camelCase."""
    response = await _login(client)
    data = response.json()["data"]
    headers = {"Authorization": f"Bearer {data['access_token']}"}

    logout = await client.post("/api/v1/auth/logout", json={"refreshToken": data["refresh_token"]}, headers=headers)
    assert logout.status_code == 200, logout.text

    replay = await client.post("/api/v1/auth/refresh", json={"refresh_token": data["refresh_token"]})
    assert replay.status_code == 401


async def test_refresh_fails_closed_when_denylist_unavailable(client, monkeypatch):
    """If the revocation store (Redis) is unreachable, refresh must be denied
    rather than accepted (fail closed)."""
    response = await _login(client)
    refresh_token = response.json()["data"]["refresh_token"]

    import app.modules.auth.service as auth_service

    class BrokenRedis:
        async def exists(self, *args, **kwargs):
            raise RuntimeError("redis unavailable")

    monkeypatch.setattr(auth_service, "get_redis", lambda: BrokenRedis())

    refresh = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert refresh.status_code == 401, refresh.text


async def test_e2e_security_settings_persist_and_lockout(client):
    """Security settings persist (no longer frontend-only) and the configured
    max login attempts actually locks the account."""
    from tests.utils import admin_headers

    admin = await admin_headers(client)
    patched = await client.patch(
        "/api/v1/settings/app-config",
        json={"security": {"maxLoginAttempts": 2, "accountLockMinutes": 1, "jwtRefreshTokenDays": 21}},
        headers=admin,
    )
    assert patched.status_code == 200, patched.text
    security = patched.json()["data"]["security"]
    assert security["maxLoginAttempts"] == 2
    assert security["accountLockMinutes"] == 1
    assert security["jwtRefreshTokenDays"] == 21

    try:
        target = "lockout-target@example.com"
        for _ in range(2):
            response = await client.post(
                "/api/v1/auth/login", json={"email": target, "password": "wrong-password"}
            )
            assert response.status_code == 401, response.text

        locked = await client.post(
            "/api/v1/auth/login", json={"email": target, "password": "wrong-password"}
        )
        assert locked.status_code == 429, locked.text
    finally:
        await client.patch(
            "/api/v1/settings/app-config",
            json={"security": {"maxLoginAttempts": 5, "accountLockMinutes": 15, "jwtRefreshTokenDays": 14}},
            headers=admin,
        )
