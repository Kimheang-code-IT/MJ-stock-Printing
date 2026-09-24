import pytest

from tests.utils import admin_headers, create_user_with_role, deactivate_then_delete, login

VIEWER_EMAIL = "viewer@example.com"
VIEWER_PASSWORD = "viewerpass1"


@pytest.fixture
async def viewer_headers(client, db_session):
    await create_user_with_role(
        db_session, email=VIEWER_EMAIL, password=VIEWER_PASSWORD, role_name="Viewer", permissions=["category.view"]
    )
    await db_session.commit()
    data = await login(client, VIEWER_EMAIL, VIEWER_PASSWORD)
    return {"Authorization": f"Bearer {data['access_token']}"}


async def test_category_crud_flow(client):
    headers = await admin_headers(client)

    created = await client.post(
        "/api/v1/categories",
        json={"code": "BEV", "name": "Beverages", "description": "Drinks"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    category = created.json()["data"]

    dup = await client.post("/api/v1/categories", json={"code": "BEV", "name": "Dup"}, headers=headers)
    assert dup.status_code == 409

    patched = await client.patch(
        f"/api/v1/categories/{category['id']}", json={"name": "Soft Drinks", "status": "ACTIVE"}, headers=headers
    )
    assert patched.status_code == 200
    assert patched.json()["data"]["name"] == "Soft Drinks"

    listing = await client.get("/api/v1/categories?q=soft", headers=headers)
    assert listing.status_code == 200
    assert listing.json()["meta"]["total"] >= 1

    active_blocked = await client.delete(f"/api/v1/categories/{category['id']}", headers=headers)
    assert active_blocked.status_code == 409
    assert "deactivate" in active_blocked.json()["detail"]["message"].lower()

    deleted = await deactivate_then_delete(client, headers, f"/api/v1/categories/{category['id']}")
    assert deleted.status_code == 200

    missing = await client.get(f"/api/v1/categories/{category['id']}", headers=headers)
    assert missing.status_code == 404


async def test_category_requires_code(client):
    """Setup > Categories requires a non-empty, unique code."""
    headers = await admin_headers(client)

    missing = await client.post("/api/v1/categories", json={"name": "No Code"}, headers=headers)
    assert missing.status_code == 422, missing.text
    assert "code" in missing.json()["detail"]["field_errors"]

    blank = await client.post("/api/v1/categories", json={"code": "", "name": "Blank Code"}, headers=headers)
    assert blank.status_code == 422, blank.text

    created = await client.post(
        "/api/v1/categories", json={"code": "REQ-1", "name": "With Code", "status": "ACTIVE"}, headers=headers
    )
    assert created.status_code == 201, created.text
    assert created.json()["data"]["code"] == "REQ-1"


async def test_category_view_only_cannot_create(client, viewer_headers):
    response = await client.post(
        "/api/v1/categories", json={"code": "NOPE2", "name": "Nope"}, headers=viewer_headers
    )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "ACCESS_DENIED"


async def test_category_delete_blocked_when_products_exist(client):
    headers = await admin_headers(client)
    category = (
        await client.post("/api/v1/categories", json={"code": "SNK", "name": "Snacks"}, headers=headers)
    ).json()["data"]
    product = await client.post(
        "/api/v1/products",
        json={"sku": "SNK-001", "name": "Chips", "category_id": category["id"], "selling_price": "2.50"},
        headers=headers,
    )
    assert product.status_code == 201, product.text

    blocked = await client.delete(f"/api/v1/categories/{category['id']}", headers=headers)
    assert blocked.status_code == 409

    await deactivate_then_delete(client, headers, f"/api/v1/products/{product.json()['data']['id']}")
    await client.patch(f"/api/v1/categories/{category['id']}", json={"status": "INACTIVE"}, headers=headers)
    unblocked = await client.delete(f"/api/v1/categories/{category['id']}", headers=headers)
    assert unblocked.status_code == 200
