"""Purchase edit (PATCH /stock/in/{id}): reverse receipt, reapply lines, totals."""

from decimal import Decimal

import pytest

from tests.utils import admin_headers


async def _make_product(client, headers, sku: str) -> dict:
    category = (
        await client.post(
            "/api/v1/categories", json={"code": f"C-{sku}", "name": f"Cat {sku}"}, headers=headers
        )
    ).json()["data"]
    return (
        await client.post(
            "/api/v1/products",
            json={
                "sku": sku,
                "name": f"Widget {sku}",
                "category_id": category["id"],
                "selling_price": "10.00",
            },
            headers=headers,
        )
    ).json()["data"]


async def _balance(client, headers, product_id) -> Decimal:
    response = await client.get(f"/api/v1/products/{product_id}", headers=headers)
    return Decimal(response.json()["data"]["quantity"])


@pytest.mark.asyncio
async def test_purchase_edit_reverses_and_reapplies(client):
    headers = await admin_headers(client)
    product = await _make_product(client, headers, "PE-1")

    created = await client.post(
        "/api/v1/stock/in",
        json={
            "paid_amount": "20.00",
            "items": [{"product_id": product["id"], "quantity": "10", "unit_cost": "2.00"}],
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    doc = created.json()["data"]
    assert await _balance(client, headers, product["id"]) == Decimal("10.0000")

    edited = await client.patch(
        f"/api/v1/stock/in/{doc['id']}",
        json={"items": [{"product_id": product["id"], "quantity": "6", "unit_cost": "2.00"}]},
        headers=headers,
    )
    assert edited.status_code == 200, edited.text
    updated = edited.json()["data"]
    assert Decimal(updated["total_amount"]) == Decimal("12.00")
    assert await _balance(client, headers, product["id"]) == Decimal("6.0000")


@pytest.mark.asyncio
async def test_purchase_edit_recalculates_supplier_debt(client):
    headers = await admin_headers(client)
    product = await _make_product(client, headers, "PE-2")
    supplier = (
        await client.post(
            "/api/v1/suppliers",
            json={"code": "SUP-PE-2", "name": "Edit Supplier", "status": "ACTIVE"},
            headers=headers,
        )
    ).json()["data"]

    created = await client.post(
        "/api/v1/stock/in",
        json={
            "supplier_id": supplier["id"],
            "paid_amount": "0",
            "items": [{"product_id": product["id"], "quantity": "10", "unit_cost": "2.00"}],
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    doc = created.json()["data"]

    edited = await client.patch(
        f"/api/v1/stock/in/{doc['id']}",
        json={"items": [{"product_id": product["id"], "quantity": "4", "unit_cost": "2.00"}]},
        headers=headers,
    )
    assert edited.status_code == 200, edited.text
    updated = edited.json()["data"]
    assert Decimal(updated["total_amount"]) == Decimal("8.00")
    assert Decimal(updated["paid_amount"]) == Decimal("0.00")
    assert updated["debt_created"] is True
