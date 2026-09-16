"""POS customer handling (spec §2.1.6 / §5.11).

Covers the walk-in default for anonymous cash sales, the rejection of credit
sales without a registered customer, and the POS "Add new customer" flow
(create via POST /customers, then sell on credit to it).
"""

from decimal import Decimal

import pytest

from tests.modules.pos.helpers import balance_of, make_stocked_product
from tests.utils import admin_headers


async def _walk_in(client, headers) -> dict:
    listing = await client.get("/api/v1/customers?q=walk-in", headers=headers)
    assert listing.status_code == 200, listing.text
    return next(c for c in listing.json()["data"] if c["is_walk_in"])


def _sale_payload(product_id: str, **extra) -> dict:
    return {
        "payment_method": "CASH",
        "amount_received": "1000.00",
        "items": [{"product_id": product_id, "quantity": "2"}],
        **extra,
    }


@pytest.mark.asyncio
async def test_walk_in_is_the_default_customer_for_anonymous_cash_sale(client):
    headers = await admin_headers(client)
    product = await make_stocked_product(client, headers, sku="POSC-1", name="Walk-in Widget")
    walk_in = await _walk_in(client, headers)

    response = await client.post("/api/v1/pos/sales", json=_sale_payload(product["id"]), headers=headers)
    assert response.status_code == 201, response.text
    sale = response.json()["data"]

    # No customer sent → the seeded walk-in customer owns the sale, no debt.
    assert sale["customer_id"] == walk_in["id"]
    assert "walk-in" in str(sale["customer_name"]).lower()
    assert Decimal(sale["debt_amount"]) == Decimal("0.00")
    assert sale["payment_status"] == "PAID"


@pytest.mark.asyncio
async def test_credit_sale_without_customer_is_rejected(client):
    """Walk-in cannot buy on credit — a registered customer is required."""
    headers = await admin_headers(client)
    product = await make_stocked_product(client, headers, sku="POSC-2", name="No Debt Widget")

    response = await client.post(
        "/api/v1/pos/sales",
        json=_sale_payload(product["id"], payment_method="CUSTOMER_DEBT", amount_received="0.00"),
        headers=headers,
    )
    assert response.status_code == 422, response.text
    assert "customer_id" in response.json()["detail"].get("field_errors", {})

    # The rejected sale must not have moved stock.
    assert await balance_of(client, headers, product["id"]) == Decimal("10.0000")


@pytest.mark.asyncio
async def test_explicitly_selected_walk_in_cannot_buy_on_credit(client):
    headers = await admin_headers(client)
    product = await make_stocked_product(client, headers, sku="POSC-3", name="Explicit Walk-in Widget")
    walk_in = await _walk_in(client, headers)

    response = await client.post(
        "/api/v1/pos/sales",
        json=_sale_payload(
            product["id"],
            payment_method="CUSTOMER_DEBT",
            amount_received="0.00",
            customer_id=walk_in["id"],
        ),
        headers=headers,
    )
    assert response.status_code == 422, response.text
    assert "customer_id" in response.json()["detail"].get("field_errors", {})


@pytest.mark.asyncio
async def test_pos_auto_created_customer_can_buy_on_credit(client):
    """POS 'Add new customer' (POST /customers) → select it → credit sale."""
    headers = await admin_headers(client)
    product = await make_stocked_product(client, headers, sku="POSC-4", name="New Customer Widget")

    created = await client.post(
        "/api/v1/customers",
        json={
            "name": "POS Walkthrough Buyer",
            "phone": "012345678",
            "location": "Phnom Penh",
            # The POS dialog sends 'Active'; the HTTP repository uppercases it.
            "status": "ACTIVE",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    customer = created.json()["data"]
    assert customer["code"].startswith("CUS-")
    assert customer["is_walk_in"] is False

    response = await client.post(
        "/api/v1/pos/sales",
        json=_sale_payload(
            product["id"],
            payment_method="CUSTOMER_DEBT",
            amount_received="0.00",
            customer_id=customer["id"],
        ),
        headers=headers,
    )
    assert response.status_code == 201, response.text
    sale = response.json()["data"]
    assert sale["customer_id"] == customer["id"]
    assert sale["customer_name"] == "POS Walkthrough Buyer"
    assert sale["payment_status"] == "UNPAID"

    # The debt is attached to the new customer for the full sale total.
    debts = await client.get(f"/api/v1/customers/{customer['id']}/debts", headers=headers)
    assert debts.status_code == 200, debts.text
    rows = debts.json()["data"]
    assert len(rows) == 1
    assert Decimal(rows[0]["remaining_amount"]) == Decimal(sale["grand_total"])
    assert rows[0]["status"] == "UNPAID"


@pytest.mark.asyncio
async def test_pos_customer_debt_deposit_sets_partial_status(client):
    """A deposit on a credit sale leaves the balance PARTIAL (not UNPAID)."""
    headers = await admin_headers(client)
    product = await make_stocked_product(client, headers, sku="POSC-5", name="Partial Debt Widget")
    customer = (
        await client.post("/api/v1/customers", json={"name": "Partial Buyer"}, headers=headers)
    ).json()["data"]

    # 2 × 10.00 = 20.00 total; 5.00 deposit → 15.00 on account.
    response = await client.post(
        "/api/v1/pos/sales",
        json=_sale_payload(
            product["id"],
            payment_method="CUSTOMER_DEBT",
            amount_received="5.00",
            customer_id=customer["id"],
        ),
        headers=headers,
    )
    assert response.status_code == 201, response.text
    sale = response.json()["data"]
    assert sale["payment_status"] == "PARTIAL"
    assert Decimal(sale["debt_amount"]) == Decimal("15.00")

    debts = (await client.get(f"/api/v1/customers/{customer['id']}/debts", headers=headers)).json()["data"]
    assert debts[0]["status"] == "PARTIAL"
    assert Decimal(debts[0]["remaining_amount"]) == Decimal("15.00")
