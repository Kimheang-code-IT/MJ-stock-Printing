import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from tests.utils import admin_headers


async def _make_product(client, headers, *, sku: str, name: str):
    category = (
        await client.post(
            "/api/v1/categories", json={"code": f"C-{sku}", "name": f"Cat {sku}"}, headers=headers
        )
    ).json()["data"]
    product = (
        await client.post(
            "/api/v1/products",
            json={
                "sku": sku,
                "name": name,
                "category_id": category["id"],
                "selling_price": "10.00",
            },
            headers=headers,
        )
    ).json()["data"]
    return product


async def _balance(client, headers, product_id) -> dict:
    response = await client.get(f"/api/v1/products/{product_id}", headers=headers)
    data = response.json()["data"]
    return {"quantity": Decimal(data["quantity"]), "average_cost": Decimal(data["average_cost"])}


async def test_stock_in_weighted_average_and_movements(client):
    headers = await admin_headers(client)
    product = await _make_product(client, headers, sku="SI-1", name="Stock In Widget")

    first = await client.post(
        "/api/v1/stock/in",
        json={
            "paid_amount": "20.00",
            "items": [{"product_id": product["id"], "quantity": "10", "unit_cost": "2.00"}],
        },
        headers=headers,
    )
    assert first.status_code == 201, first.text
    doc1 = first.json()["data"]
    assert doc1["document_no"].startswith("STI-")
    assert doc1["total_amount"] == "20.00"
    assert doc1["items"][0]["product_name"] == "Stock In Widget"

    balance = await _balance(client, headers, product["id"])
    assert balance["quantity"] == Decimal("10.0000")
    assert balance["average_cost"] == Decimal("2.00")

    second = await client.post(
        "/api/v1/stock/in",
        json={
            "paid_amount": "40.00",
            "items": [{"product_id": product["id"], "quantity": "10", "unit_cost": "4.00"}],
        },
        headers=headers,
    )
    assert second.status_code == 201
    balance = await _balance(client, headers, product["id"])
    assert balance["quantity"] == Decimal("20.0000")
    assert balance["average_cost"] == Decimal("3.00"), "weighted average cost must update"

    movements = await client.get(
        f"/api/v1/stock/movements?product_id={product['id']}", headers=headers
    )
    assert movements.status_code == 200
    assert movements.json()["meta"]["total"] == 2
    assert all(m["movement_type"] == "STOCK_IN" for m in movements.json()["data"])

    history = await client.get(f"/api/v1/stock/products/{product['id']}/history", headers=headers)
    assert history.status_code == 200
    assert history.json()["meta"]["total"] == 2


async def test_stock_in_supplier_debt_partial_and_full(client):
    headers = await admin_headers(client)
    supplier = (
        await client.post("/api/v1/suppliers", json={"name": "Debt Supplier"}, headers=headers)
    ).json()["data"]
    product = await _make_product(client, headers, sku="SI-2", name="Debt Widget")

    partial = await client.post(
        "/api/v1/stock/in",
        json={
            "supplier_id": supplier["id"],
            "paid_amount": "5.00",
            "items": [{"product_id": product["id"], "quantity": "10", "unit_cost": "1.00"}],
        },
        headers=headers,
    )
    assert partial.status_code == 201, partial.text
    data = partial.json()["data"]
    assert data["debt_created"] is True
    assert data["paid_amount"] == "5.00"

    debts = await client.get(f"/api/v1/suppliers/{supplier['id']}/debts", headers=headers)
    assert debts.status_code == 200
    debt = debts.json()["data"][0]
    assert debt["original_amount"] == "10.00"
    assert debt["paid_amount"] == "5.00"
    assert debt["remaining_amount"] == "5.00"
    assert debt["status"] == "PARTIAL"
    assert debt["document_no"] == data["document_no"]

    history = await client.get(
        f"/api/v1/suppliers/{supplier['id']}/history", headers=headers
    )
    assert history.status_code == 200
    assert history.json()["meta"]["total"] == 1
    assert history.json()["data"][0]["document_no"] == data["document_no"]

    full = await client.post(
        "/api/v1/stock/in",
        json={
            "supplier_id": supplier["id"],
            "paid_amount": "4.00",
            "items": [{"product_id": product["id"], "quantity": "4", "unit_cost": "1.00"}],
        },
        headers=headers,
    )
    assert full.status_code == 201
    assert full.json()["data"]["debt_created"] is False


async def test_stock_in_tax_total_and_debt(client):
    """Purchase footer adjustment: total = subtotal + tax; the
    supplier debt (and payment cap) use the adjusted total."""
    headers = await admin_headers(client)
    supplier = (
        await client.post("/api/v1/suppliers", json={"name": "Tax Supplier"}, headers=headers)
    ).json()["data"]
    product = await _make_product(client, headers, sku="SI-TAX", name="Tax Widget")

    # Subtotal 10 × 2.00 = 20.00 → + 4.00 tax = 24.00 total.
    response = await client.post(
        "/api/v1/stock/in",
        json={
            "supplier_id": supplier["id"],
            "tax_amount": "4.00",
            "paid_amount": "14.00",
            "items": [{"product_id": product["id"], "quantity": "10", "unit_cost": "2.00"}],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["tax_amount"] == "4.00"
    assert data["total_amount"] == "24.00"
    assert data["paid_amount"] == "14.00"
    assert data["debt_created"] is True

    debts = await client.get(f"/api/v1/suppliers/{supplier['id']}/debts", headers=headers)
    assert debts.status_code == 200
    debt = debts.json()["data"][0]
    assert debt["original_amount"] == "24.00"
    assert debt["remaining_amount"] == "10.00"

    # Negative amounts are rejected by the schema.
    negative = await client.post(
        "/api/v1/stock/in",
        json={
            "tax_amount": "-1.00",
            "paid_amount": "0",
            "items": [{"product_id": product["id"], "quantity": "1", "unit_cost": "2.00"}],
        },
        headers=headers,
    )
    assert negative.status_code == 422


async def test_stock_in_requires_full_payment_without_supplier(client):
    headers = await admin_headers(client)
    product = await _make_product(client, headers, sku="SI-3", name="Cash Widget")
    response = await client.post(
        "/api/v1/stock/in",
        json={
            "paid_amount": "0",
            "items": [{"product_id": product["id"], "quantity": "5", "unit_cost": "2.00"}],
        },
        headers=headers,
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "VALIDATION_ERROR"


async def test_adjustment_in_out_and_audit(client, db_session):
    from sqlalchemy import select

    from app.shared.audit.models import AuditLog

    headers = await admin_headers(client)
    product = await _make_product(client, headers, sku="ADJ-1", name="Adjust Widget")

    await client.post(
        "/api/v1/stock/in",
        json={
            "paid_amount": "10.00",
            "items": [{"product_id": product["id"], "quantity": "10", "unit_cost": "1.00"}],
        },
        headers=headers,
    )

    counted = await client.post(
        "/api/v1/stock/adjust",
        json={
            "items": [
                {
                    "product_id": product["id"],
                    "actual_quantity": "12",
                    "reason": "Recount found extra units",
                }
            ]
        },
        headers=headers,
    )
    assert counted.status_code == 201, counted.text
    item = counted.json()["data"]["items"][0]
    assert Decimal(item["system_quantity"]) == Decimal("10")
    assert Decimal(item["actual_quantity"]) == Decimal("12")
    assert Decimal(item["quantity"]) == Decimal("2")

    counted_out = await client.post(
        "/api/v1/stock/adjust",
        json={
            "items": [
                {
                    "product_id": product["id"],
                    "system_quantity": "12",
                    "actual_quantity": "9",
                    "reason": "Shrinkage",
                }
            ]
        },
        headers=headers,
    )
    assert counted_out.status_code == 201
    assert Decimal(counted_out.json()["data"]["items"][0]["quantity"]) == Decimal("-3")

    balance = await _balance(client, headers, product["id"])
    assert balance["quantity"] == Decimal("9.0000")

    audit = await db_session.scalar(
        select(AuditLog).where(AuditLog.action == "stock_adjustment").order_by(AuditLog.created_at.desc())
    )
    assert audit is not None

    missing_reason = await client.post(
        "/api/v1/stock/adjust",
        json={"items": [{"product_id": product["id"], "actual_quantity": "9"}]},
        headers=headers,
    )
    assert missing_reason.status_code == 422


async def test_damage_rules(client, db_session):
    from sqlalchemy import select

    from app.shared.audit.models import AuditLog

    headers = await admin_headers(client)
    product = await _make_product(client, headers, sku="DMG-1", name="Damage Widget")

    await client.post(
        "/api/v1/stock/in",
        json={
            "paid_amount": "10.00",
            "items": [{"product_id": product["id"], "quantity": "10", "unit_cost": "1.00"}],
        },
        headers=headers,
    )

    damaged = await client.post(
        "/api/v1/stock/damage",
        json={
            "items": [
                {"product_id": product["id"], "quantity": "2", "reason": "Broken on shelf"}
            ]
        },
        headers=headers,
    )
    assert damaged.status_code == 201, damaged.text
    doc = damaged.json()["data"]
    assert doc["document_no"].startswith("DMG-")
    assert Decimal(doc["total_amount"]) == Decimal("2.00")

    balance = await _balance(client, headers, product["id"])
    assert balance["quantity"] == Decimal("8.0000")

    audit = await db_session.scalar(
        select(AuditLog).where(AuditLog.action == "stock_damage").order_by(AuditLog.created_at.desc())
    )
    assert audit is not None

    # Damage without a reason is rejected.
    no_reason = await client.post(
        "/api/v1/stock/damage", json={"items": [{"product_id": product["id"], "quantity": "1"}]},
        headers=headers,
    )
    assert no_reason.status_code == 422


async def test_oversell_rejected_unless_setting_allows(client):
    headers = await admin_headers(client)
    product = await _make_product(client, headers, sku="NEG-1", name="Negative Widget")

    # Start from a neutral state regardless of other suites.
    await client.patch(
        "/api/v1/admin/settings",
        json={"values": {"pos": {"allow_negative_stock": False}}},
        headers=headers,
    )

    rejected = await client.post(
        "/api/v1/stock/damage",
        json={"items": [{"product_id": product["id"], "quantity": "5", "reason": "beyond stock"}]},
        headers=headers,
    )
    assert rejected.status_code == 409
    assert "Insufficient stock" in rejected.json()["detail"]["message"]

    # Enable allow_negative_stock and retry.
    await client.get("/api/v1/admin/settings", headers=headers)
    patched = await client.patch(
        "/api/v1/admin/settings",
        json={"values": {"pos": {"allow_negative_stock": True}}},
        headers=headers,
    )
    assert patched.status_code == 200

    allowed = await client.post(
        "/api/v1/stock/damage",
        json={"items": [{"product_id": product["id"], "quantity": "5", "reason": "allowed negative"}]},
        headers=headers,
    )
    assert allowed.status_code == 201, allowed.text
    balance = await _balance(client, headers, product["id"])
    assert balance["quantity"] == Decimal("-5.0000")

    # Restore the setting.
    await client.patch(
        "/api/v1/admin/settings",
        json={"values": {"pos": {"allow_negative_stock": False}}},
        headers=headers,
    )


async def test_stock_in_rollback_on_failure(client):
    headers = await admin_headers(client)
    product = await _make_product(client, headers, sku="RB-1", name="Rollback Widget")

    # No supplier + partial payment fails AFTER movements were staged: everything
    # must roll back (balance unchanged, no movements persisted).
    response = await client.post(
        "/api/v1/stock/in",
        json={
            "paid_amount": "1.00",
            "items": [{"product_id": product["id"], "quantity": "7", "unit_cost": "1.00"}],
        },
        headers=headers,
    )
    assert response.status_code == 422

    balance = await _balance(client, headers, product["id"])
    assert balance["quantity"] == Decimal("0.0000")
    movements = await client.get(
        f"/api/v1/stock/movements?product_id={product['id']}", headers=headers
    )
    assert movements.json()["meta"]["total"] == 0


async def test_concurrent_outbound_only_one_succeeds(client):
    headers = await admin_headers(client)
    product = await _make_product(client, headers, sku="CC-1", name="Concurrent Widget")
    await client.patch(
        "/api/v1/admin/settings",
        json={"values": {"pos": {"allow_negative_stock": False}}},
        headers=headers,
    )
    await client.post(
        "/api/v1/stock/in",
        json={
            "paid_amount": "5.00",
            "items": [{"product_id": product["id"], "quantity": "5", "unit_cost": "1.00"}],
        },
        headers=headers,
    )

    async def damage():
        return await client.post(
            "/api/v1/stock/damage",
            json={"items": [{"product_id": product["id"], "quantity": "5", "reason": "race"}]},
            headers=headers,
        )

    results = await asyncio.gather(damage(), damage())
    statuses = sorted(r.status_code for r in results)
    assert statuses == [201, 409], f"exactly one concurrent outbound must succeed: {statuses}"
    balance = await _balance(client, headers, product["id"])
    assert balance["quantity"] == Decimal("0.0000")

async def test_stock_in_khr_currency_debt_and_out(client):
    """Document currency: a KHR purchase records every amount in KHR and the
    supplier debt inherits the KHR currency."""
    headers = await admin_headers(client)
    supplier = (
        await client.post("/api/v1/suppliers", json={"name": "KHR Supplier"}, headers=headers)
    ).json()["data"]
    product = await _make_product(client, headers, sku="SI-KHR", name="KHR Widget")

    # Subtotal 100 × 10000 = 1,000,000 KHR → paid 410,000 → debt 590,000 KHR.
    response = await client.post(
        "/api/v1/stock/in",
        json={
            "supplier_id": supplier["id"],
            "currency": "KHR",
            "exchange_rate": "41000",
            "paid_amount": "410000",
            # Yesterday — keeps today's Finance aggregates untouched.
            "transaction_date": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
            "items": [{"product_id": product["id"], "quantity": "100", "unit_cost": "10000"}],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    assert data["currency"] == "KHR"
    assert Decimal(data["exchange_rate"]) == Decimal("41000")
    assert Decimal(data["total_amount"]) == Decimal("1000000.00")
    assert data["debt_created"] is True

    debts = await client.get(f"/api/v1/suppliers/{supplier['id']}/debts", headers=headers)
    assert debts.status_code == 200
    debt = debts.json()["data"][0]
    assert debt["currency"] == "KHR"
    assert Decimal(debt["remaining_amount"]) == Decimal("590000.00")


async def test_stock_in_sold_by_area_uses_height_times_width(client):
    """Height × Width (m) becomes the received m² quantity and is persisted."""
    headers = await admin_headers(client)
    product = await _make_product(client, headers, sku="SI-AREA", name="Area Widget")

    response = await client.post(
        "/api/v1/stock/in",
        json={
            "paid_amount": "60.00",
            "items": [{"product_id": product["id"], "quantity": "1", "unit_cost": "10.00", "height": "2", "width": "3"}],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    data = response.json()["data"]
    item = data["items"][0]
    # quantity was overridden by the area: 2 × 3 = 6 m² × $10.00 = $60.00.
    assert Decimal(item["quantity"]) == Decimal("6.0000")
    assert Decimal(item["height"]) == Decimal("2.0000")
    assert Decimal(item["width"]) == Decimal("3.0000")
    assert Decimal(item["area_m2"]) == Decimal("6.0000")
    assert Decimal(data["total_amount"]) == Decimal("60.00")

    balance = await _balance(client, headers, product["id"])
    assert balance["quantity"] == Decimal("6.0000")

    # Height without width is rejected.
    invalid = await client.post(
        "/api/v1/stock/in",
        json={
            "paid_amount": "10.00",
            "items": [{"product_id": product["id"], "quantity": "1", "unit_cost": "10.00", "height": "2"}],
        },
        headers=headers,
    )
    assert invalid.status_code == 422



