from sqlalchemy import select

from app.modules.auth.models import User
from tests.modules.pos.helpers import make_stocked_product
from tests.utils import admin_headers, deactivate_then_delete


async def test_product_crud_sku_conflict_and_price_audit(client, db_session):
    headers = await admin_headers(client)
    category = (
        await client.post("/api/v1/categories", json={"code": "GEN", "name": "General"}, headers=headers)
    ).json()["data"]

    created = await client.post(
        "/api/v1/products",
        json={
            "sku": "SKU-0001",
            "name": "Coffee 500g",
            "category_id": category["id"],
            "cost_price": "4.00",
            "selling_price": "6.50",
            "minimum_stock": "5",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    product = created.json()["data"]
    assert float(product["quantity"]) == 0.0
    assert product["category_name"] == "General"

    dup_sku = await client.post(
        "/api/v1/products",
        json={"sku": "SKU-0001", "name": "Dup", "category_id": category["id"], "selling_price": "1"},
        headers=headers,
    )
    assert dup_sku.status_code == 409

    patched = await client.patch(
        f"/api/v1/products/{product['id']}", json={"selling_price": "7.25"}, headers=headers
    )
    assert patched.status_code == 200
    assert patched.json()["data"]["selling_price"] == "7.25"

    # A selling-price change is applied directly to the product (POS charges it).
    detail = await client.get(f"/api/v1/products/{product['id']}", headers=headers)
    assert detail.json()["data"]["selling_price"] == "7.25"

    # Price change must be audited.
    result = await db_session.execute(
        select(User).where(User.email == "admin@gmail.com")
    )
    admin = result.scalar_one()
    from app.shared.audit.models import AuditLog

    audit = await db_session.scalar(
        select(AuditLog)
        .where(AuditLog.action == "price_changed", AuditLog.entity_id == product["id"])
        .order_by(AuditLog.created_at.desc())
    )
    assert audit is not None
    assert audit.user_id == admin.id
    assert audit.new_values["selling_price"] == "7.25"

    # Cannot read products without authentication.
    anon = await client.get("/api/v1/products")
    assert anon.status_code == 401

    # Cleanup
    await deactivate_then_delete(client, headers, f"/api/v1/products/{product['id']}")
    await deactivate_then_delete(client, headers, f"/api/v1/categories/{category['id']}")

async def test_sku_optional_and_unique(client):
    """SKU is the optional internal code: unique when set, omitted otherwise."""
    headers = await admin_headers(client)
    category = (
        await client.post("/api/v1/categories", json={"code": "BAR", "name": "Sku"}, headers=headers)
    ).json()["data"]

    # 1. Create without sku.
    no_sku = await client.post(
        "/api/v1/products",
        json={
            "name": "No SKU Product",
            "category_id": category["id"],
            "selling_price": "2.00",
        },
        headers=headers,
    )
    assert no_sku.status_code == 201, no_sku.text
    auto = no_sku.json()["data"]
    assert auto["sku"] is None

    # 2. Duplicate sku rejected.
    first = await client.post(
        "/api/v1/products",
        json={"sku": "SKU-DUP", "name": "First", "category_id": category["id"], "selling_price": "1.00"},
        headers=headers,
    )
    assert first.status_code == 201, first.text
    dup = await client.post(
        "/api/v1/products",
        json={"sku": "SKU-DUP", "name": "Dup", "category_id": category["id"], "selling_price": "1.00"},
        headers=headers,
    )
    assert dup.status_code == 409

    # 3. Product list search matches the sku.
    listing = await client.get("/api/v1/products?q=SKU-DUP", headers=headers)
    assert listing.status_code == 200
    assert any(row["id"] == first.json()["data"]["id"] for row in listing.json()["data"])

    await deactivate_then_delete(client, headers, f"/api/v1/products/{auto['id']}")
    await deactivate_then_delete(client, headers, f"/api/v1/products/{first.json()['data']['id']}")
    await deactivate_then_delete(client, headers, f"/api/v1/categories/{category['id']}")


async def test_product_delete_blocked_by_sale_history_then_deactivate(client):
    """A product sold at least once must not be hard-deleted; deactivate instead."""
    headers = await admin_headers(client)
    product = await make_stocked_product(
        client, headers, sku="PRDH-1", name="Product History Widget", qty="10"
    )

    sale = await client.post(
        "/api/v1/pos/sales",
        json={
            "payment_method": "CASH",
            "amount_received": "100.00",
            "items": [{"product_id": product["id"], "quantity": "1"}],
        },
        headers=headers,
    )
    assert sale.status_code == 201, sale.text

    blocked = await client.delete(f"/api/v1/products/{product['id']}", headers=headers)
    assert blocked.status_code == 409
    assert "deactivate" in blocked.json()["detail"]["message"].lower()

    deactivated = await client.patch(
        f"/api/v1/products/{product['id']}", json={"status": "INACTIVE"}, headers=headers
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["data"]["status"] == "INACTIVE"


async def test_product_delete_blocked_by_stock_in_history(client):
    """A product with a recorded stock-in is part of stock history: no hard delete."""
    headers = await admin_headers(client)
    product = await make_stocked_product(
        client, headers, sku="PRDS-1", name="Product Stock Widget", qty="3"
    )
    blocked = await client.delete(f"/api/v1/products/{product['id']}", headers=headers)
    assert blocked.status_code == 409
    assert "deactivate" in blocked.json()["detail"]["message"].lower()


async def test_product_default_supplier_stored_shown_and_cleared(client):
    """A product keeps an optional default supplier (fast-purchase prefill)."""
    headers = await admin_headers(client)
    category = (
        await client.post("/api/v1/categories", json={"code": "SUP", "name": "Supplier"}, headers=headers)
    ).json()["data"]
    supplier = (
        await client.post(
            "/api/v1/suppliers",
            json={"name": "Default Vendor", "phone": "012345678"},
            headers=headers,
        )
    ).json()["data"]

    created = await client.post(
        "/api/v1/products",
        json={
            "name": "Supplier Product",
            "category_id": category["id"],
            "selling_price": "3.00",
            "supplier_id": supplier["id"],
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    product = created.json()["data"]
    assert product["supplier_id"] == supplier["id"]
    assert product["supplier_name"] == "Default Vendor"

    # Detail read keeps the supplier.
    detail = await client.get(f"/api/v1/products/{product['id']}", headers=headers)
    assert detail.json()["data"]["supplier_id"] == supplier["id"]

    # Explicit null clears the default supplier.
    cleared = await client.patch(
        f"/api/v1/products/{product['id']}", json={"supplier_id": None}, headers=headers
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["data"]["supplier_id"] is None

    # Unknown supplier is rejected.
    unknown = await client.patch(
        f"/api/v1/products/{product['id']}",
        json={"supplier_id": "00000000-0000-0000-0000-000000000000"},
        headers=headers,
    )
    assert unknown.status_code == 404

    await deactivate_then_delete(client, headers, f"/api/v1/products/{product['id']}")
    await deactivate_then_delete(client, headers, f"/api/v1/categories/{category['id']}")
