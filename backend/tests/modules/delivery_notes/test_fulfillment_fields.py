"""Delivery Notes — extended fulfillment fields, statuses and derived invoice status.

Covers the expanded delivery-note form (delivery date, driver, vehicle,
delivery fee, received-by, currency), the extended status vocabulary
(PENDING / PREPARING / OUT_FOR_DELIVERY / PARTIALLY_DELIVERED / DELIVERED /
FAILED / RETURNED), per-invoice derived delivery status, and the invariants
that survive the vocabulary change: same-customer invoices, remaining-qty
validation, no stock mutation, atomicity and permissions.
"""

import asyncio
import uuid
from decimal import Decimal

import pytest

from tests.modules.pos.helpers import balance_of, make_customer, make_stocked_product
from tests.utils import admin_headers, create_user_with_role, login


async def _sale(client, headers, product, customer_id: str, qty: str):
    sale = await client.post(
        "/api/v1/pos/sales",
        json={
            "payment_method": "CASH",
            "amount_received": "500.00",
            "customer_id": customer_id,
            "items": [{"product_id": product["id"], "quantity": qty}],
        },
        headers=headers,
    )
    assert sale.status_code == 201, sale.text
    data = sale.json()["data"]
    return data, data["items"][0]["id"]


async def _two_sales_one_customer(client, headers, tag: str):
    product = await make_stocked_product(client, headers, sku=f"DNF-{tag}", name=f"DN Fulfill {tag}", qty="20")
    customer = await make_customer(client, headers, code=f"DN-F-{tag}", name=f"DN Fulfill Cust {tag}")
    sale_a, line_a = await _sale(client, headers, product, customer["id"], "4")
    sale_b, line_b = await _sale(client, headers, product, customer["id"], "3")
    return product, customer, sale_a, line_a, sale_b, line_b


@pytest.mark.asyncio
async def test_create_with_fulfillment_fields_and_initial_status(client):
    headers = await admin_headers(client)
    tag = uuid.uuid4().hex[:6]
    product, customer, sale, line_a, _sale_b, _line_b = await _two_sales_one_customer(client, headers, tag)

    created = await client.post(
        "/api/v1/delivery-notes",
        json={
            "customerId": customer["id"],
            "deliveryPhone": "0123456789",
            "deliveryLocation": "Phnom Penh",
            "driverName": "Dara Kim",
            "vehicleNo": "1AB-1234",
            "deliveryDate": "2026-09-12",
            "deliveryFee": "5.25",
            "receivedBy": "Sokha Chan",
            "currency": "USD",
            "status": "PREPARING",
            "note": "Handle with care",
            "lines": [{"saleId": sale["id"], "saleItemId": line_a, "qtyToDeliver": "2", "note": "Fragile box"}],
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    note = created.json()["data"]
    assert note["status"] == "PREPARING"
    assert note["driver_name"] == "Dara Kim"
    assert note["vehicle_no"] == "1AB-1234"
    assert note["delivery_date"].startswith("2026-09-12")
    assert Decimal(note["delivery_fee"]) == Decimal("5.25")
    assert note["received_by"] == "Sokha Chan"
    assert note["currency"] == "USD"
    assert note["items"][0]["note"] == "Fragile box"

    # The note still never mutates stock (20 stocked - 4 sold on A - 3 sold on B).
    assert await balance_of(client, headers, product["id"]) == Decimal("13.0000")


@pytest.mark.asyncio
async def test_status_vocabulary_and_transitions(client):
    """PARTIALLY_DELIVERED / FAILED exist; FAILED needs a reason; terminals stay terminal."""
    headers = await admin_headers(client)
    tag = uuid.uuid4().hex[:6]
    _product, _customer, sale, line_a, _sale_b, _line_b = await _two_sales_one_customer(client, headers, tag)

    note = (
        await client.post(
            "/api/v1/delivery-notes",
            json={
                "deliveryPhone": "0123456789",
                "deliveryLocation": "Phnom Penh",
                "lines": [{"saleId": sale["id"], "saleItemId": line_a, "qtyToDeliver": "4"}],
            },
            headers=headers,
        )
    ).json()["data"]

    # FAILED without a reason is rejected.
    failed = await client.post(
        f"/api/v1/delivery-notes/{note['id']}/status",
        json={"status": "FAILED", "cancel_reason": "driver unavailable"},
        headers=headers,
    )
    assert failed.status_code == 409  # PENDING → FAILED is not a legal transition

    preparing = await client.post(
        f"/api/v1/delivery-notes/{note['id']}/status", json={"status": "PREPARING"}, headers=headers
    )
    assert preparing.status_code == 200

    no_reason = await client.post(
        f"/api/v1/delivery-notes/{note['id']}/status", json={"status": "FAILED"}, headers=headers
    )
    assert no_reason.status_code == 422

    out = await client.post(
        f"/api/v1/delivery-notes/{note['id']}/status", json={"status": "OUT_FOR_DELIVERY"}, headers=headers
    )
    assert out.status_code == 200

    partial = await client.post(
        f"/api/v1/delivery-notes/{note['id']}/status",
        json={"status": "PARTIALLY_DELIVERED"},
        headers=headers,
    )
    assert partial.status_code == 200, partial.text
    assert partial.json()["data"]["status"] == "PARTIALLY_DELIVERED"

    delivered = await client.post(
        f"/api/v1/delivery-notes/{note['id']}/status", json={"status": "DELIVERED"}, headers=headers
    )
    assert delivered.status_code == 200
    assert delivered.json()["data"]["status"] == "DELIVERED"

    # DELIVERED is terminal even for the new statuses.
    late = await client.post(
        f"/api/v1/delivery-notes/{note['id']}/status",
        json={"status": "FAILED", "cancel_reason": "late"},
        headers=headers,
    )
    assert late.status_code == 409


@pytest.mark.asyncio
async def test_derived_invoice_delivery_status(client):
    """Invoice delivery status derives from delivered quantities across notes."""
    headers = await admin_headers(client)
    tag = uuid.uuid4().hex[:6]
    product = await make_stocked_product(client, headers, sku=f"DND-{tag}", name=f"DN Derived {tag}", qty="12")
    customer = await make_customer(client, headers, code=f"DN-D-{tag}", name=f"DN Derived Cust {tag}")
    sale, line_id = await _sale(client, headers, product, customer["id"], "4")

    # First partial note delivers 1 of 4 → PARTIALLY_DELIVERED.
    first = (
        await client.post(
            "/api/v1/delivery-notes",
            json={
                "deliveryPhone": "0123456789",
                "deliveryLocation": "Phnom Penh",
                "status": "DELIVERED",
                "lines": [{"saleId": sale["id"], "saleItemId": line_id, "qtyToDeliver": "1"}],
            },
            headers=headers,
        )
    ).json()["data"]
    assert first["status"] == "DELIVERED"

    picker = (
        await client.get(
            f"/api/v1/delivery-notes/deliverable-invoices?customer_id={customer['id']}", headers=headers
        )
    ).json()["data"]
    row = next(r for r in picker if r["sale_id"] == sale["id"])
    assert row["delivery_status"] == "PARTIALLY_DELIVERED"

    # Second note completes the invoice (3 remaining) → FULLY_DELIVERED and
    # the invoice leaves the picker.
    second = await client.post(
        "/api/v1/delivery-notes",
        json={
            "deliveryPhone": "0123456789",
            "deliveryLocation": "Phnom Penh",
            "status": "DELIVERED",
            "lines": [{"saleId": sale["id"], "saleItemId": line_id, "qtyToDeliver": "3"}],
        },
        headers=headers,
    )
    assert second.status_code == 201, second.text

    picker = (
        await client.get(
            f"/api/v1/delivery-notes/deliverable-invoices?customer_id={customer['id']}", headers=headers
        )
    ).json()["data"]
    assert all(r["sale_id"] != sale["id"] for r in picker)

    # Detail view of the first note shows the derived FULLY_DELIVERED status.
    detail = (await client.get(f"/api/v1/delivery-notes/{first['id']}", headers=headers)).json()["data"]
    assert detail["sales"][0]["delivery_status"] == "FULLY_DELIVERED"


@pytest.mark.asyncio
async def test_concurrent_partial_deliveries_no_over_delivery(client):
    """Same invoice in multiple notes under concurrency: rows lock, no over-delivery."""
    headers = await admin_headers(client)
    tag = uuid.uuid4().hex[:6]
    product = await make_stocked_product(client, headers, sku=f"DNC2-{tag}", name=f"DN Conc2 {tag}", qty="10")
    customer = await make_customer(client, headers, code=f"DN-C2-{tag}", name=f"DN Conc2 Cust {tag}")
    sale, line_id = await _sale(client, headers, product, customer["id"], "4")

    async def create(qty: str):
        return await client.post(
            "/api/v1/delivery-notes",
            json={
                "deliveryPhone": "0123456789",
                "deliveryLocation": "Phnom Penh",
                "status": "DELIVERED",
                "lines": [{"saleId": sale["id"], "saleItemId": line_id, "qtyToDeliver": qty}],
            },
            headers=headers,
        )

    first, second, third = await asyncio.gather(create("3"), create("3"), create("3"))
    # 4 total deliverable: exactly one of the three racing creates must win.
    created = [r for r in (first, second, third) if r.status_code == 201]
    rejected = [r for r in (first, second, third) if r.status_code == 422]
    assert len(created) == 1 and len(rejected) == 2, (first.text, second.text, third.text)

    # One more unit still fits; the next one is rejected.
    assert (await create("1")).status_code == 201
    assert (await create("1")).status_code == 422
    assert await balance_of(client, headers, product["id"]) == Decimal("6.0000")


@pytest.mark.asyncio
async def test_new_statuses_permission_gated(client, db_session):
    """PARTIALLY_DELIVERED requires delivery.deliver; FAILED requires delivery.cancel."""
    await create_user_with_role(
        db_session,
        email="dn-ext@example.com",
        password="dnext1",
        role_name="DN Ext Viewer",
        permissions=["delivery.view", "delivery.confirm"],
    )
    await db_session.commit()
    data = await login(client, "dn-ext@example.com", "dnext1")
    preparer = {"Authorization": f"Bearer {data['access_token']}"}

    headers = await admin_headers(client)
    tag = uuid.uuid4().hex[:6]
    _product, _customer, sale, line_a, _sale_b, _line_b = await _two_sales_one_customer(client, headers, tag)
    note = (
        await client.post(
            "/api/v1/delivery-notes",
            json={
                "deliveryPhone": "0123456789",
                "deliveryLocation": "Phnom Penh",
                "lines": [{"saleId": sale["id"], "saleItemId": line_a, "qtyToDeliver": "1"}],
            },
            headers=headers,
        )
    ).json()["data"]

    # Preparer can move to PREPARING / OUT_FOR_DELIVERY...
    assert (
        await client.post(
            f"/api/v1/delivery-notes/{note['id']}/status", json={"status": "PREPARING"}, headers=preparer
        )
    ).status_code == 200
    assert (
        await client.post(
            f"/api/v1/delivery-notes/{note['id']}/status", json={"status": "OUT_FOR_DELIVERY"}, headers=preparer
        )
    ).status_code == 200

    # ...but not to PARTIALLY_DELIVERED (needs delivery.deliver).
    forbidden = await client.post(
        f"/api/v1/delivery-notes/{note['id']}/status",
        json={"status": "PARTIALLY_DELIVERED"},
        headers=preparer,
    )
    assert forbidden.status_code == 403

    # FAILED (delivery.cancel) is forbidden for this role too.
    failed = await client.post(
        f"/api/v1/delivery-notes/{note['id']}/status",
        json={"status": "FAILED", "cancel_reason": "x"},
        headers=preparer,
    )
    assert failed.status_code == 403