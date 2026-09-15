"""SPA settings surface: App Info / App Config projection + connectivity tests."""

from tests.utils import admin_headers


async def test_app_config_requires_authentication(client):
    response = await client.get("/api/v1/settings/app-config")
    assert response.status_code == 401


async def test_app_config_exposes_full_document(client):
    headers = await admin_headers(client)
    response = await client.get("/api/v1/settings/app-config", headers=headers)
    assert response.status_code == 200, response.text
    config = response.json()["data"]
    for section in ("general", "localization", "email", "telegram", "stock", "notifications", "security", "system"):
        assert section in config, f"missing App Config section {section}"
    assert config["telegram"]["botToken"] == ""
    assert set(config["stock"]) >= {"lowStockLevel", "expiryAlert1Days", "expiryAlert2Days"}


async def test_app_info_round_trip_and_reset(client):
    headers = await admin_headers(client)

    updated = await client.patch(
        "/api/v1/settings/app-info",
        json={"businessName": "Surface Test Pharmacy", "supportEmail": "ops@example.com"},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    info = updated.json()["data"]
    assert info["businessName"] == "Surface Test Pharmacy"
    assert info["supportEmail"] == "ops@example.com"

    config = (await client.get("/api/v1/settings/app-config", headers=headers)).json()["data"]
    assert config["telegram"]["botDisplayName"] == "Surface Test Pharmacy"

    reset = await client.post("/api/v1/settings/app-info/reset", headers=headers)
    assert reset.status_code == 200, reset.text
    assert reset.json()["data"]["businessName"] == "Yoeun Sokhon Pharmacy"


async def test_app_config_write_accepts_payment_invoice_toggle(client):
    headers = await admin_headers(client)

    # Regression: the SPA writes payment_invoice_notify_enabled via /admin/settings.
    patched = await client.patch(
        "/api/v1/admin/settings",
        json={"values": {"telegram": {"payment_invoice_notify_enabled": False}}},
        headers=headers,
    )
    assert patched.status_code == 200, patched.text

    config = (await client.get("/api/v1/settings/app-config", headers=headers)).json()["data"]
    assert config["telegram"]["paymentInvoiceNotifyEnabled"] is False

    restored = await client.patch(
        "/api/v1/admin/settings",
        json={"values": {"telegram": {"payment_invoice_notify_enabled": True}}},
        headers=headers,
    )
    assert restored.status_code == 200


async def test_email_and_telegram_connection_tests_report_status(client):
    headers = await admin_headers(client)

    email = await client.post("/api/v1/settings/app-config/email/test-connection", headers=headers)
    assert email.status_code == 200
    assert email.json()["data"]["status"] == "disabled"

    # Telegram token is empty in tests, so the master switch reports disabled.
    telegram = await client.post("/api/v1/settings/app-config/telegram/send-test", headers=headers)
    assert telegram.status_code == 200
    assert telegram.json()["data"]["status"] == "disabled"


async def test_reset_data_is_refused(client):
    headers = await admin_headers(client)
    response = await client.post("/api/v1/settings/reset-data", headers=headers)
    assert response.status_code == 501
    assert response.json()["detail"]["code"] == "FEATURE_DISABLED"


async def test_reference_options_endpoints(client):
    headers = await admin_headers(client)
    for path in ("/api/v1/admin/roles/options", "/api/v1/suppliers/options", "/api/v1/customers/options"):
        response = await client.get(path, headers=headers)
        assert response.status_code == 200, f"{path}: {response.text}"
        assert isinstance(response.json()["data"], list)
