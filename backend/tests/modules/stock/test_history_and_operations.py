"""History-dialog kind filters + GET/POST /stock/operations read model."""

import uuid
from decimal import Decimal

import pytest

from tests.modules.pos.helpers import make_stocked_product
from tests.utils import admin_headers


@pytest.mark.asyncio
async def test_history_kind_rows_and_display_labels(client):
    headers = await admin_headers(client)
    tag = uuid.uuid4().hex[:6]
    product = await make_stocked_product(client, headers, sku=f"KIND-{tag}", name=f"Kind Widget {tag}", qty="6")
    pid = product["id"]

    sale = await client.post(
        "/api/v1/pos/sales",
        json={"payment_method": "CASH", "amount_received": "100.00", "items": [{"product_id": pid, "quantity": "2"}]},
        headers=headers,
    )
    assert sale.status_code == 201, sale.text

    sale_return = await client.post(
        f"/api/v1/pos/sales/{sale.json()['data']['id']}/return",
        json={"reason": "wrong color", "items": [{"sale_item_id": sale.json()["data"]["items"][0]["id"], "quantity": "1", "restock": True}]},
        headers=headers,
    )
    assert sale_return.status_code == 201, sale_return.text

    stock_in = await client.get(f"/api/v1/stock/products/{pid}/history?type=stock_in", headers=headers)
    in_rows = stock_in.json()["data"]
    kinds = {row["kind"] for row in in_rows}
    types = {row["type"] for row in in_rows}
    assert kinds == {"stock_in"}
    assert types == {"Stock In", "Sale Return"}
    # Stock In dialog columns: product name and per-unit price.
    assert all(row["product"] == product["name"] for row in in_rows)
    assert all(Decimal(row["unit_price"]) > 0 for row in in_rows)

    stock_out = await client.get(f"/api/v1/stock/products/{pid}/history?type=stock_out", headers=headers)
    out_rows = stock_out.json()["data"]
    assert {row["type"] for row in out_rows} == {"Sale"}
    assert all(Decimal(row["qty"]) < 0 for row in out_rows)
    # Stock Out dialog columns: invoice no, product, unit price.
    assert all(row["reference"] for row in out_rows)
    assert all(row["product"] == product["name"] for row in out_rows)
    assert all(Decimal(row["unit_price"]) > 0 for row in out_rows)
    # SALE rows carry the sale linkage for the invoice detail click-through.
    assert all(row["reference_type"] == "sale" for row in out_rows)
    assert all(row["reference_id"] for row in out_rows)


@pytest.mark.asyncio
async def test_movement_invoice_click_through(client):
    """Clicking an Invoice No on a SALE stock-out row opens the invoice detail."""
    headers = await admin_headers(client)
    tag = uuid.uuid4().hex[:6]
    product = await make_stocked_product(client, headers, sku=f"INV-{tag}", name=f"Invoice Widget {tag}", qty="8")
    pid = product["id"]

    sale = await client.post(
        "/api/v1/pos/sales",
        json={"payment_method": "CASH", "amount_received": "100.00", "items": [{"product_id": pid, "quantity": "3"}]},
        headers=headers,
    )
    assert sale.status_code == 201, sale.text
    invoice_no = sale.json()["data"]["invoice_no"]

    history = await client.get(f"/api/v1/stock/products/{pid}/history?type=stock_out", headers=headers)
    row = next(r for r in history.json()["data"] if r["reference"] == invoice_no)

    detail = await client.get(f"/api/v1/stock/movements/{row['id']}/invoice", headers=headers)
    assert detail.status_code == 200, detail.text
    data = detail.json()["data"]
    assert data["invoice_no"] == invoice_no
    assert any(str(item["name"]).startswith(product["name"]) for item in data["items"])

    # Non-sale movements have no invoice.
    in_history = await client.get(f"/api/v1/stock/products/{pid}/history?type=stock_in", headers=headers)
    in_row = in_history.json()["data"][0]
    rejected = await client.get(f"/api/v1/stock/movements/{in_row['id']}/invoice", headers=headers)
    assert rejected.status_code in (400, 404, 422)


@pytest.mark.asyncio
async def test_stock_operations_list_and_quick_create(client):
    headers = await admin_headers(client)
    tag = uuid.uuid4().hex[:6]
    product = await make_stocked_product(client, headers, sku=f"OPS-{tag}", name=f"Ops Widget {tag}", qty="10")

    # Quick stock-in through the generic operations endpoint.
    created = await client.post(
        "/api/v1/stock/operations",
        json={
            "type": "stock_in",
            "productId": product["id"],
            "quantity": 4,
            "unitCost": "2.50",
            "note": "quick op",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    record = created.json()["data"]
    assert record["reference"]
    assert record["product"] == product["name"]

    listing = await client.get("/api/v1/stock/operations", headers=headers)
    assert listing.status_code == 200, listing.text
    docs = listing.json()["data"]
    doc = next(d for d in docs if d["id"] == record["id"])
    assert doc["purchase_no"] if "purchase_no" in doc else doc["purchaseNo"]
    assert doc["items"]
    item = doc["items"][0]
    assert item["productId"] == product["id"]
    assert Decimal(item["price"]) == Decimal("2.50")
    assert Decimal(item["quantity"]) == Decimal("4.0000")
    assert Decimal(doc["total"]) == Decimal("10.00")

    # The cost-price dialog source of truth: productId/price/quantity per item.
    assert item["name"] == product["name"]
