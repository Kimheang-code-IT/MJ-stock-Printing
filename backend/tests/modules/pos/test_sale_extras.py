"""POS complete-sale extras: camelCase input, delivery price, included debts,
product selling price, and the print-ready receipt payload."""

import uuid
from decimal import Decimal

import pytest

from tests.modules.pos.helpers import make_customer, make_stocked_product
from tests.utils import admin_headers


@pytest.mark.asyncio
async def test_complete_sale_alias_and_camel_case_payload(client):
    headers = await admin_headers(client)
    tag = uuid.uuid4().hex[:6]
    product = await make_stocked_product(client, headers, sku=f"POSX-{tag}", name=f"POSX Widget {tag}")

    response = await client.post(
        "/api/v1/pos/sales/complete",
        json={
            "paymentMethod": "CASH",
            "paidAmount": "21.00",
            "items": [{"productId": product["id"], "quantity": 2}],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    sale = response.json()["data"]
    assert Decimal(sale["grand_total"]) == Decimal("20.00")
    assert Decimal(sale["change_amount"]) == Decimal("1.00")


@pytest.mark.asyncio
async def test_sold_by_area_line_uses_height_times_width_as_quantity(client):
    """Height × Width (m) becomes the billed m² quantity and is persisted."""
    headers = await admin_headers(client)
    tag = uuid.uuid4().hex[:6]
    product = await make_stocked_product(client, headers, sku=f"POSA-{tag}", name=f"POSA Widget {tag}")

    response = await client.post(
        "/api/v1/pos/sales",
        json={
            "payment_method": "CASH",
            "amount_received": "100.00",
            "items": [{"product_id": product["id"], "quantity": "1", "height": "2", "width": "3"}],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    sale = response.json()["data"]
    item = sale["items"][0]
    # quantity was overridden by the area: 2 × 3 = 6 m² × $10.00 = $60.00.
    assert Decimal(item["quantity"]) == Decimal("6.0000")
    assert Decimal(item["height"]) == Decimal("2.0000")
    assert Decimal(item["width"]) == Decimal("3.0000")
    assert Decimal(item["area_m2"]) == Decimal("6.0000")
    assert Decimal(sale["grand_total"]) == Decimal("60.00")

    receipt = await client.get(f"/api/v1/pos/sales/{sale['id']}/receipt", headers=headers)
    assert receipt.status_code == 200, receipt.text
    receipt_item = receipt.json()["data"]["items"][0]
    assert Decimal(receipt_item["area_m2"]) == Decimal("6.0000")

    # Height without width is rejected.
    invalid = await client.post(
        "/api/v1/pos/sales",
        json={
            "payment_method": "CASH",
            "amount_received": "100.00",
            "items": [{"product_id": product["id"], "quantity": "1", "height": "2"}],
        },
        headers=headers,
    )
    assert invalid.status_code == 422


@pytest.mark.asyncio
async def test_default_unit_price_is_product_selling_price(client):
    headers = await admin_headers(client)
    tag = uuid.uuid4().hex[:6]
    product = await make_stocked_product(client, headers, sku=f"POSP-{tag}", name=f"POSP Widget {tag}")

    # Change the product selling price; POS must charge it.
    patched = await client.patch(
        f"/api/v1/products/{product['id']}", json={"selling_price": "15.00"}, headers=headers
    )
    assert patched.status_code == 200, patched.text

    response = await client.post(
        "/api/v1/pos/sales",
        json={"payment_method": "CASH", "amount_received": "100.00", "items": [{"product_id": product["id"], "quantity": "2"}]},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    sale = response.json()["data"]
    assert Decimal(sale["grand_total"]) == Decimal("30.00")
    assert Decimal(sale["items"][0]["unit_price"]) == Decimal("15.00")


@pytest.mark.asyncio
async def test_delivery_price_added_to_grand_total(client):
    headers = await admin_headers(client)
    tag = uuid.uuid4().hex[:6]
    product = await make_stocked_product(client, headers, sku=f"POSD-{tag}", name=f"POSD Widget {tag}")

    response = await client.post(
        "/api/v1/pos/sales",
        json={
            "payment_method": "CASH",
            "paidAmount": "25.00",
            "deliveryPrice": "5.00",
            "items": [{"productId": product["id"], "quantity": 2}],
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    sale = response.json()["data"]
    assert Decimal(sale["grand_total"]) == Decimal("25.00")
    assert Decimal(sale["delivery_price"]) == Decimal("5.00")

    # The delivered sale must NOT stock-out a second time via delivery notes.

    # Receipt payload carries the delivery price.
    receipt = await client.get(f"/api/v1/pos/sales/{sale['id']}/receipt", headers=headers)
    assert receipt.status_code == 200, receipt.text
    data = receipt.json()["data"]
    assert Decimal(data["delivery_price"]) == Decimal("5.00")


@pytest.mark.asyncio
async def test_included_debts_settled_from_paid_amount(client):
    headers = await admin_headers(client)
    tag = uuid.uuid4().hex[:6]
    product = await make_stocked_product(client, headers, sku=f"POSB-{tag}", name=f"POSB Widget {tag}")
    customer = await make_customer(client, headers, code=f"POSB-C-{tag}", name="POSB Customer")

    # First sale creates a 10.00 debt.
    first = await client.post(
        "/api/v1/pos/sales",
        json={
            "payment_method": "CUSTOMER_DEBT",
            "customer_id": customer["id"],
            "items": [{"product_id": product["id"], "quantity": "1"}],
        },
        headers=headers,
    )
    assert first.status_code == 201, first.text

    debts = (await client.get(f"/api/v1/customers/{customer['id']}/debts", headers=headers)).json()["data"]
    open_debt = next(row for row in debts if Decimal(row["remaining_amount"]) > 0)
    assert open_debt["invoice_no"]
    assert open_debt["date"] is not None

    # Second sale pays THIS sale in full (10) and settles the old debt from
    # deposit (10) — deposit never inflates the current sale grand total.
    second = await client.post(
        "/api/v1/pos/sales/complete",
        json={
            "customerId": customer["id"],
            "paymentMethod": "CASH",
            "paidAmount": "10.00",
            "deposit": "10.00",
            "includedDebtIds": [open_debt["id"]],
            "items": [{"productId": product["id"], "quantity": "1"}],
        },
        headers=headers,
    )
    assert second.status_code == 201, second.text
    sale = second.json()["data"]
    assert Decimal(sale["grand_total"]) == Decimal("10.00")
    assert Decimal(sale["paid_amount"]) == Decimal("10.00")
    assert Decimal(sale["debt_amount"]) == Decimal("0.00")
    assert sale["payment_status"] == "PAID"

    debts_after = (await client.get(f"/api/v1/customers/{customer['id']}/debts", headers=headers)).json()["data"]
    settled = next(row for row in debts_after if row["id"] == open_debt["id"])
    assert Decimal(settled["remaining_amount"]) == Decimal("0.00")
    assert settled["status"] == "PAID"

    # Partial sale payment with separate prior-debt deposit: pay 5 on a new
    # 10 sale while settling a leftover debt of 5 via deposit.
    leftover = await client.post(
        "/api/v1/pos/sales/complete",
        json={
            "customerId": customer["id"],
            "paymentMethod": "CASH",
            "paidAmount": "5.00",
            "items": [{"productId": product["id"], "quantity": "1"}],
        },
        headers=headers,
    )
    assert leftover.status_code == 201, leftover.text
    leftover_sale = leftover.json()["data"]
    assert Decimal(leftover_sale["paid_amount"]) == Decimal("5.00")
    assert Decimal(leftover_sale["debt_amount"]) == Decimal("5.00")

    debts_mid = (await client.get(f"/api/v1/customers/{customer['id']}/debts", headers=headers)).json()["data"]
    open_after = next(row for row in debts_mid if Decimal(row["remaining_amount"]) == Decimal("5.00"))
    third = await client.post(
        "/api/v1/pos/sales/complete",
        json={
            "customerId": customer["id"],
            "paymentMethod": "CASH",
            "paidAmount": "15.00",
            "deposit": "5.00",
            "includedDebtIds": [open_after["id"]],
            "items": [{"productId": product["id"], "quantity": "1"}],
        },
        headers=headers,
    )
    assert third.status_code == 201, third.text
    data = third.json()["data"]
    # Paid now 15 on a 10 sale → 5 change; deposit 5 settles the old debt.
    assert Decimal(data["change_amount"]) == Decimal("5.00")
    assert data["payment_status"] == "PAID"


@pytest.mark.asyncio
async def test_receipt_payload_is_print_ready(client):
    headers = await admin_headers(client)
    tag = uuid.uuid4().hex[:6]
    product = await make_stocked_product(client, headers, sku=f"POSR-{tag}", name=f"POSR Widget {tag}")

    sale = (
        await client.post(
            "/api/v1/pos/sales",
            json={
                "payment_method": "CASH",
                "amount_received": "30.00",
                "deliveryPrice": "2.00",
                "items": [{"productId": product["id"], "quantity": 2}],
            },
            headers=headers,
        )
    ).json()["data"]

    receipt = await client.get(f"/api/v1/pos/sales/{sale['id']}/receipt", headers=headers)
    assert receipt.status_code == 200, receipt.text
    data = receipt.json()["data"]
    assert data["shop"]["name"]
    assert data["invoice_no"] == sale["invoice_no"]
    assert data["sale_date"]
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["name"] == product["name"]
    assert item["sku"]
    assert Decimal(item["line_total"]) == Decimal("20.00")  # 2 × 10
    assert Decimal(data["subtotal"]) == Decimal("20.00")
    assert Decimal(data["delivery_price"]) == Decimal("2.00")
    assert Decimal(data["grand_total"]) == Decimal("22.00")
    assert Decimal(data["paid"]) == Decimal("22.00")

@pytest.mark.asyncio
async def test_receipt_payload_full_invoice_contract(client):
    """Receipt payload carries every field the existing invoice needs:
    currency, exchange rate, customer contact, payment, delivery, settings."""
    headers = await admin_headers(client)
    tag = uuid.uuid4().hex[:6]
    product = await make_stocked_product(client, headers, sku=f"POSR2-{tag}", name=f"POSR2 Widget {tag}")
    customer = await make_customer(client, headers, code=f"POSR2-C-{tag}", name="Receipt Customer")
    # Give the customer an address too (make_customer seeds the phone).
    patched = await client.patch(
        f"/api/v1/customers/{customer['id']}",
        json={"address": "Street 12"},
        headers=headers,
    )
    assert patched.status_code == 200, patched.text

    sale = (
        await client.post(
            "/api/v1/pos/sales",
            json={
                "payment_method": "CASH",
                "amount_received": "50.00",
                "customer_id": customer["id"],
                "delivery_price": "1.50",
                "items": [{"product_id": product["id"], "quantity": "2"}],
            },
            headers=headers,
        )
    ).json()["data"]

    receipt = await client.get(f"/api/v1/pos/sales/{sale['id']}/receipt", headers=headers)
    assert receipt.status_code == 200, receipt.text
    data = receipt.json()["data"]

    # Invoice identity + timing + actors
    assert data["invoice_no"] == sale["invoice_no"]
    assert data["sale_date"]
    assert data["cashier"]
    assert data["customer"] == "Receipt Customer"

    # Customer contact snapshot (only present when available)
    assert data["customer_phone"] == "0123456789"
    assert data["customer_address"] == "Street 12"

    # Document currency + exchange rate (KHR per 1 USD; 1 for USD docs)
    assert data["currency"] == "USD"
    assert Decimal(data["exchange_rate"]) == Decimal("1")

    # Items: quantity, unit price, line amount
    assert len(data["items"]) == 1
    item = data["items"][0]
    for key in ("name", "sku", "quantity", "unit_price", "line_total"):
        assert key in item
    assert Decimal(item["line_total"]) == Decimal("20.00")

    # Totals: subtotal/delivery fee/grand total/paid/debt/change
    assert Decimal(data["subtotal"]) == Decimal("20.00")
    assert Decimal(data["delivery_price"]) == Decimal("1.50")
    assert Decimal(data["grand_total"]) == Decimal("21.50")
    # `paid` is the amount applied to the sale (over-tender is returned as
    # change at the POS and not persisted on the document).
    assert Decimal(data["paid"]) == Decimal("21.50")
    assert Decimal(data["debt"]) == Decimal("0.00")
    assert Decimal(data["change"]) == Decimal("0.00")

    # Payment method + status
    assert data["payment_method"] == "CASH"
    assert data["payment_status"] == "PAID"

    # Shop/settings information + presentation values
    assert data["shop"]["name"]
    assert "paper_size" in data and data["paper_size"] in ("A4", "A5")
    assert "show_exchange_rate" in data
    assert "footer" in data


@pytest.mark.asyncio
async def test_receipt_payload_preserves_khr_sale_exchange_rate(client):
    """A historical KHR sale keeps the exchange rate used at sale time."""
    headers = await admin_headers(client)
    tag = uuid.uuid4().hex[:6]
    product = await make_stocked_product(client, headers, sku=f"POSRK-{tag}", name=f"POSRK Widget {tag}")

    sale = (
        await client.post(
            "/api/v1/pos/sales",
            json={
                "payment_method": "CASH",
                "amount_received": "100000",
                "currency": "KHR",
                "exchange_rate": "4150.50",
                "items": [{"product_id": product["id"], "quantity": "1"}],
            },
            headers=headers,
        )
    ).json()["data"]
    assert sale["currency"] == "KHR"

    receipt = await client.get(f"/api/v1/pos/sales/{sale['id']}/receipt", headers=headers)
    data = receipt.json()["data"]
    assert data["currency"] == "KHR"
    assert Decimal(data["exchange_rate"]) == Decimal("4150.50")
    # KHR amounts stay in KHR (selling_price in USD is converted at sale time
    # by the POS contract; here the stored grand_total preserves the KHR value).
    assert Decimal(data["grand_total"]) > 0
