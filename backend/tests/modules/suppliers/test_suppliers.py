from tests.utils import DEFAULT_UOM_ID, admin_headers, deactivate_then_delete


async def test_supplier_crud_with_auto_code(client):
    headers = await admin_headers(client)

    created = await client.post(
        "/api/v1/suppliers",
        json={"name": "Acme Trading", "company_name": "Acme Co Ltd", "phone": "012345678"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    supplier = created.json()["data"]
    assert supplier["code"].startswith("SUP-")

    patched = await client.patch(
        f"/api/v1/suppliers/{supplier['id']}", json={"contact_person": "Dara"}, headers=headers
    )
    assert patched.status_code == 200
    assert patched.json()["data"]["contact_person"] == "Dara"

    listing = await client.get("/api/v1/suppliers?q=acme", headers=headers)
    assert listing.status_code == 200
    assert listing.json()["meta"]["total"] >= 1

    deleted = await deactivate_then_delete(client, headers, f"/api/v1/suppliers/{supplier['id']}")
    assert deleted.status_code == 200


async def test_supplier_requires_view_permission(client):
    anon = await client.get("/api/v1/suppliers")
    assert anon.status_code == 401


async def test_supplier_delete_blocked_by_purchase_history_then_deactivate(client):
    """A supplier with purchase history must not be hard-deleted; deactivate instead."""
    headers = await admin_headers(client)

    supplier = (
        await client.post(
            "/api/v1/suppliers", json={"name": "History Supplier", "phone": "011111111"}, headers=headers
        )
    ).json()["data"]
    category = (
        await client.post("/api/v1/categories", json={"code": "SUPH", "name": "Sup Cat"}, headers=headers)
    ).json()["data"]
    product = (
        await client.post(
            "/api/v1/products",
            json={
                "sku": "SUPH-1",
                "name": "Supplier History Product",
                "category_id": category["id"],
                "uom_id": str(DEFAULT_UOM_ID),
                "selling_price": "5.00",
            },
            headers=headers,
        )
    ).json()["data"]
    stock_in = await client.post(
        "/api/v1/stock/in",
        json={
            "supplier_id": supplier["id"],
            "paid_amount": "20.00",
            "items": [{"product_id": product["id"], "quantity": "10", "unit_cost": "2.00"}],
        },
        headers=headers,
    )
    assert stock_in.status_code == 201, stock_in.text

    blocked = await client.delete(f"/api/v1/suppliers/{supplier['id']}", headers=headers)
    assert blocked.status_code == 409
    assert "deactivate" in blocked.json()["detail"]["message"].lower()

    # The supplier remains deactivatable, so business history stays intact.
    deactivated = await client.patch(
        f"/api/v1/suppliers/{supplier['id']}", json={"status": "INACTIVE"}, headers=headers
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["data"]["status"] == "INACTIVE"
