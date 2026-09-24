"""Finance Report contracts: /finance/summary alias, ledger row shape,
and Dashboard/Finance agreement on Expense (spec 2.1.10)."""

import uuid
from decimal import Decimal

import pytest

from tests.modules.pos.helpers import make_stocked_product
from tests.utils import admin_headers


@pytest.mark.asyncio
async def test_finance_summary_alias_matches_finance(client):
    headers = await admin_headers(client)
    tag = uuid.uuid4().hex[:6]
    await make_stocked_product(client, headers, sku=f"FINA-{tag}", name=f"Fin Alias {tag}")

    finance = await client.get("/api/v1/reports/finance", headers=headers)
    summary = await client.get("/api/v1/reports/finance/summary", headers=headers)
    assert finance.status_code == 200, finance.text
    assert summary.status_code == 200, summary.text

    data = summary.json()["data"]
    # The frontend financeSummary mapper reads these aliases.
    assert Decimal(data["income"]) == Decimal(data["total_sales"])
    assert Decimal(data["expense"]) == Decimal(data["total_expense"])
    assert Decimal(data["expense"]) == (
        Decimal(data["operating_expenses"]) + Decimal(data["supplier_payments"])
    )
    assert Decimal(data["net"]) == Decimal(data["net_result"])
    assert Decimal(data["outstanding"]) == (
        Decimal(data["total_customer_debt"]) + Decimal(data["total_supplier_debt"])
    )


@pytest.mark.asyncio
async def test_finance_entry_rows_expose_mapper_fields(client):
    headers = await admin_headers(client)
    tag = uuid.uuid4().hex[:6]
    product = await make_stocked_product(client, headers, sku=f"FENT-{tag}", name=f"Fin Entry {tag}")

    sale = await client.post(
        "/api/v1/pos/sales",
        json={"payment_method": "CASH", "amount_received": "20.00", "items": [{"product_id": product["id"], "quantity": "2"}]},
        headers=headers,
    )
    assert sale.status_code == 201, sale.text
    invoice_no = sale.json()["data"]["invoice_no"]

    expense = await client.post(
        "/api/v1/reports/finance/expenses",
        json={"date": "2030-06-01", "category": "Transport", "amount": "7.50", "paymentMethod": "CASH"},
        headers=headers,
    )
    assert expense.status_code == 201, expense.text

    entries = await client.get(
        "/api/v1/reports/finance/entries?type=expense&startDate=2030-05-01&endDate=2030-06-30", headers=headers
    )
    assert entries.status_code == 200, entries.text
    rows = entries.json()["data"]
    expense_row = next(row for row in rows if row["id"] == expense.json()["data"]["id"])
    assert expense_row["type"] == "expense"
    assert expense_row["category"] == "Transport"
    assert expense_row["paymentMethod"] == "CASH"
    assert expense_row["user"]
    assert Decimal(expense_row["amount"]) == Decimal("7.50")

    income_page = await client.get(f"/api/v1/reports/finance/entries?q={invoice_no}", headers=headers)
    rows = income_page.json()["data"]
    income_row = next(row for row in rows if row["type"] == "income")
    assert income_row["reference"] == invoice_no
    assert income_row["category"] in ("Sales", "SALES")
    assert income_row["user"]


@pytest.mark.asyncio
async def test_dashboard_matches_finance_ledger(client):
    """Dashboard Income/Expense KPIs == the Finance Report ledger (cash basis)."""
    headers = await admin_headers(client)
    baseline = (await client.get("/api/v1/dashboard/summary?period=7d", headers=headers)).json()["data"]

    tag = uuid.uuid4().hex[:6]
    product = await make_stocked_product(client, headers, sku=f"DASHF-{tag}", name=f"Dash Fin {tag}")

    sale = await client.post(
        "/api/v1/pos/sales",
        json={"payment_method": "CASH", "amount_received": "50.00", "items": [{"product_id": product["id"], "quantity": "5"}]},
        headers=headers,
    )
    assert sale.status_code == 201, sale.text

    expense_date = sale.json()["data"]["sale_date"][:10]
    created = await client.post(
        "/api/v1/reports/finance/expenses",
        json={"date": expense_date, "category": "Utilities", "amount": "12.00", "payment_method": "CASH"},
        headers=headers,
    )
    assert created.status_code == 201, created.text

    dashboard = (await client.get("/api/v1/dashboard/summary?period=7d", headers=headers)).json()["data"]
    finance = (
        await client.get(
            f"/api/v1/reports/finance/summary?startDate={dashboard['period_start']}&endDate={dashboard['period_end']}",
            headers=headers,
        )
    ).json()["data"]

    # Income KPI = cash actually received (the $50 checkout tender), not accrual sales.
    assert Decimal(dashboard["summary"]["total_income"]) - Decimal(
        baseline["summary"]["total_income"]
    ) == Decimal("50.00")
    # Expense KPI = supplier payment ($20 stock-in) + operating expense ($12);
    # equals the finance summary total_expense for the same dates.
    assert Decimal(dashboard["summary"]["total_expense"]) - Decimal(
        baseline["summary"]["total_expense"]
    ) == Decimal("32.00")
    assert Decimal(dashboard["summary"]["total_expense"]) == Decimal(finance["total_expense"])
    # Chart series reconcile with the period totals.
    chart_income = sum((Decimal(row["income"]) for row in dashboard["chart"]), Decimal("0"))
    chart_expense = sum((Decimal(row["expense"]) for row in dashboard["chart"]), Decimal("0"))
    assert chart_income == Decimal(dashboard["summary"]["total_income"])
    assert chart_expense == Decimal(dashboard["summary"]["total_expense"])
