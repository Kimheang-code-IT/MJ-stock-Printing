"""Refresh endpoint honors the configured per-IP rate limit."""

import uuid

from tests.utils import login


async def test_refresh_is_rate_limited(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "rate_limit_refresh_per_minute", 1)

    # Unique source IP so the Redis counter is not shared with other tests.
    ip = f"203.0.113.{uuid.uuid4().int % 250 + 1}"
    headers = {"X-Forwarded-For": ip}

    data = await login(client, "admin@gmail.com", "123456")
    refresh_token = data["refresh_token"]

    first = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token}, headers=headers)
    assert first.status_code == 200, first.text

    rotated = first.json()["data"]["refresh_token"]
    second = await client.post("/api/v1/auth/refresh", json={"refresh_token": rotated}, headers=headers)
    assert second.status_code == 429, second.text
