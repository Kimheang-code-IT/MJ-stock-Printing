"""Google Sheets backup: change detection, dedup, history and restore."""

import pytest
import pytest_asyncio

from app.modules.backup import service as backup_service
from app.modules.backup.sheets import InMemorySheetsClient
from tests.utils import admin_headers

FAKE_SERVICE_ACCOUNT = (
    '{"type":"service_account","client_email":"backup@example.iam.gserviceaccount.com",'
    '"private_key":"-----BEGIN PRIVATE KEY-----\\nMIIfake\\n-----END PRIVATE KEY-----\\n",'
    '"project_id":"mj-backup"}'
)


@pytest_asyncio.fixture(autouse=True)
async def _clean_backup_state(db_session):
    """Backup settings and the ledger live in the shared test DB — reset them."""
    from sqlalchemy import text

    for statement in (
        "DELETE FROM system_settings WHERE group_name = 'backup'",
        "DELETE FROM backup_records",
        "DELETE FROM backup_table_states",
        "DELETE FROM backup_jobs",
    ):
        await db_session.execute(text(statement))
    await db_session.commit()
    yield


async def _configure_backup(client, headers, *, enabled=True, interval=1):
    response = await client.patch(
        "/api/v1/admin/settings",
        json={
            "values": {
                "backup": {
                    "enabled": enabled,
                    "interval_hours": interval,
                    "spreadsheet_id": "spreadsheet-123",
                    "service_account_json": FAKE_SERVICE_ACCOUNT,
                }
            }
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _install_fake_client(monkeypatch) -> InMemorySheetsClient:
    fake = InMemorySheetsClient()
    monkeypatch.setattr(backup_service, "build_client", lambda config: fake)
    return fake


async def _create_category(client, headers, code: str) -> dict:
    response = await client.post(
        "/api/v1/categories",
        json={"code": code, "name": f"Category {code}"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


@pytest.mark.asyncio
async def test_backup_settings_are_masked(client):
    headers = await admin_headers(client)
    await _configure_backup(client, headers)

    response = await client.get("/api/v1/settings/app-config", headers=headers)
    assert response.status_code == 200, response.text
    backup = response.json()["data"]["backup"]
    assert backup["enabled"] is True
    assert backup["intervalHours"] == 1
    assert backup["spreadsheetId"] == "spreadsheet-123"
    assert backup["serviceAccountJson"] == "********"
    assert backup["configured"] is True


@pytest.mark.asyncio
async def test_backup_appends_new_and_changed_records(client, monkeypatch):
    headers = await admin_headers(client)
    await _configure_backup(client, headers)
    fake = _install_fake_client(monkeypatch)

    category = await _create_category(client, headers, "BK1")

    first = await client.post("/api/v1/backups/run", json={}, headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["data"]["status"] == "SUCCESS"
    assert first.json()["data"]["rows_backed_up"] >= 1

    # The category tab exists with the metadata + data columns.
    header = await fake.get_header("categories")
    assert header[:6] == [
        "backup_at",
        "backup_version",
        "table_name",
        "record_id",
        "operation",
        "record_version",
    ]
    assert "code" in header
    rows = await fake.get_rows("categories")
    category_rows = [row for row in rows[1:] if row[header.index("record_id")] == category["id"]]
    assert len(category_rows) == 1
    assert category_rows[0][header.index("operation")] == "INSERT"

    # A second run with no changes appends nothing (duplicate prevention).
    second = await client.post("/api/v1/backups/run", json={}, headers=headers)
    assert second.json()["data"]["rows_backed_up"] == 0
    rows = await fake.get_rows("categories")
    category_rows = [row for row in rows[1:] if row[header.index("record_id")] == category["id"]]
    assert len(category_rows) == 1

    # Updating the record appends a newer version instead of overwriting.
    updated = await client.patch(
        f"/api/v1/categories/{category['id']}",
        json={"name": "Renamed category"},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    third = await client.post("/api/v1/backups/run", json={}, headers=headers)
    assert third.json()["data"]["rows_backed_up"] >= 1

    rows = await fake.get_rows("categories")
    category_rows = [row for row in rows[1:] if row[header.index("record_id")] == category["id"]]
    assert len(category_rows) == 2
    versions = sorted(int(row[header.index("record_version")]) for row in category_rows)
    assert versions == [1, 2]
    assert any(row[header.index("operation")] == "UPDATE" for row in category_rows)


@pytest.mark.asyncio
async def test_backup_detects_new_columns(client, monkeypatch):
    """A schema change (new column) is added to the existing header."""
    headers = await admin_headers(client)
    await _configure_backup(client, headers)
    fake = _install_fake_client(monkeypatch)

    await _create_category(client, headers, "BK2")
    await client.post("/api/v1/backups/run", json={}, headers=headers)

    # Simulate a future schema change by appending a column to the sheet header.
    original = await fake.get_header("categories")
    await fake.set_header("categories", original + ["future_column"])
    assert "future_column" in await fake.get_header("categories")

    # A run after the change must preserve the extended header and fill blanks.
    await client.post("/api/v1/backups/run", json={}, headers=headers)
    header = await fake.get_header("categories")
    assert header[-1] == "future_column"
    rows = await fake.get_rows("categories")
    assert len(rows[0]) == len(header)


@pytest.mark.asyncio
async def test_restore_recreates_deleted_rows(client, db_session, monkeypatch):
    headers = await admin_headers(client)
    await _configure_backup(client, headers)
    _install_fake_client(monkeypatch)

    category = await _create_category(client, headers, "BK3")
    await client.post("/api/v1/backups/run", json={}, headers=headers)

    # Simulate data loss: delete the row straight from the database.
    from sqlalchemy import text

    await db_session.execute(
        text("DELETE FROM categories WHERE id = :id"), {"id": category["id"]}
    )
    await db_session.commit()

    dry = await client.post(
        "/api/v1/backups/restore",
        json={"tables": ["categories"], "dryRun": True, "confirm": True},
        headers=headers,
    )
    assert dry.status_code == 200, dry.text
    assert dry.json()["data"]["inserted"] >= 1

    restored = await client.post(
        "/api/v1/backups/restore",
        json={"tables": ["categories"], "confirm": True},
        headers=headers,
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["data"]["inserted"] >= 1

    fetched = await client.get(f"/api/v1/categories/{category['id']}", headers=headers)
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["data"]["code"] == "BK3"


@pytest.mark.asyncio
async def test_restore_requires_confirmation(client):
    headers = await admin_headers(client)
    await _configure_backup(client, headers)
    response = await client.post(
        "/api/v1/backups/restore", json={"tables": ["categories"]}, headers=headers
    )
    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_manual_backup_without_configuration_is_rejected(client):
    headers = await admin_headers(client)
    response = await client.post("/api/v1/backups/run", json={}, headers=headers)
    assert response.status_code == 422, response.text
    assert "not configured" in response.json()["detail"]["message"].lower()


@pytest.mark.asyncio
async def test_status_reports_latest_job(client, monkeypatch):
    headers = await admin_headers(client)
    await _configure_backup(client, headers)
    _install_fake_client(monkeypatch)

    await client.post("/api/v1/backups/run", json={}, headers=headers)
    response = await client.get("/api/v1/backups/status", headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["configured"] is True
    assert data["last_job"]["status"] == "SUCCESS"
    assert isinstance(data["tables"], list) and data["tables"]


@pytest.mark.asyncio
async def test_system_settings_secrets_are_masked_in_sheet(client, db_session, monkeypatch):
    headers = await admin_headers(client)
    await _configure_backup(client, headers)
    fake = _install_fake_client(monkeypatch)

    # Store a telegram token (a secret) then back it up.
    from app.modules.administration.repository import SettingsRepository

    await SettingsRepository(db_session).upsert(
        "telegram",
        "telegram.bot_token",
        "123456:secret-token-value",
        is_secret=True,
        updated_by=None,
    )
    await db_session.commit()

    await client.post("/api/v1/backups/run", json={}, headers=headers)

    rows = await fake.get_rows("system_settings")
    header = [str(value) for value in rows[0]]
    key_index = header.index("key")
    value_index = header.index("value")
    token_rows = [row for row in rows[1:] if row[key_index] == "telegram.bot_token"]
    assert token_rows
    assert token_rows[-1][value_index] == "********"
