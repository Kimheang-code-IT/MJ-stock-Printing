"""Role permission matrix API tests.

Exercises the exact endpoint the Roles & Permissions matrix writes to
(`/api/v1/admin/roles`, `/api/v1/admin/permissions`) and proves the backend
stays the security authority: restricted roles get 403 on everything they were
not granted, unknown codes are rejected, and system/Administrator roles are
protected.
"""

import uuid

from tests.utils import admin_headers, login

CASHIER_PERMISSIONS = ["dashboard.view", "pos.access", "pos.print", "stock.view"]
STOCK_STAFF_PERMISSIONS = [
    "dashboard.view",
    "stock.view",
    "product.create",
    "product.update",
    "stock.in",
    "stock.adjust",
    "stock.damage",
    "report.purchase",
]
ACCOUNTANT_PERMISSIONS = [
    "report.sales",
    "report.finance",
    "report.customer_debt",
    "report.supplier_debt",
    "customer.debt.pay",
    "supplier.debt.pay",
]


async def _create_role(client, headers, *, name: str, permissions: list[str]) -> dict:
    response = await client.post(
        "/api/v1/admin/roles",
        json={"name": name, "permissions": permissions},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def _request(client, method: str, path: str, headers: dict):
    """Issue a request; only mutating methods carry a (dummy) JSON body."""
    if method == "get":
        return await client.get(path, headers=headers)
    return await getattr(client, method)(path, json={}, headers=headers)


async def _create_user_headers(client, headers, *, role_id: str) -> dict:
    email = f"matrix-{uuid.uuid4().hex[:10]}@example.com"
    password = "restricted1"
    response = await client.post(
        "/api/v1/admin/users",
        json={"full_name": "Matrix User", "email": email, "password": password, "role_id": role_id},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    data = await login(client, email, password)
    return {"Authorization": f"Bearer {data['access_token']}"}


async def test_role_create_edit_remove_and_unknown(client):
    headers = await admin_headers(client)

    catalog = await client.get("/api/v1/admin/permissions", headers=headers)
    assert catalog.status_code == 200
    modules = {entry["module"] for entry in catalog.json()["data"]}
    # The page-oriented matrix maps onto exactly these backend modules.
    assert {
        "dashboard", "stock", "product", "pos", "delivery", "category",
        "brand", "supplier", "customer", "report", "expense", "user", "role",
        "sequence", "audit", "settings",
    } <= modules

    role = await _create_role(
        client, headers, name=f"Matrix Editor {uuid.uuid4().hex[:6]}", permissions=["pos.access", "product.update"]
    )
    assert set(role["permissions"]) == {"pos.access", "product.update"}

    role_id = role["id"]

    # Edit: replace the permission set.
    edited = await client.patch(
        f"/api/v1/admin/roles/{role_id}",
        json={"permissions": ["report.sales", "dashboard.view"]},
        headers=headers,
    )
    assert edited.status_code == 200
    assert set(edited.json()["data"]["permissions"]) == {"report.sales", "dashboard.view"}

    # Remove one permission.
    removed = await client.patch(
        f"/api/v1/admin/roles/{role_id}", json={"permissions": ["dashboard.view"]}, headers=headers
    )
    assert removed.status_code == 200
    assert set(removed.json()["data"]["permissions"]) == {"dashboard.view"}

    # Unknown codes are rejected and never partially applied.
    unknown = await client.patch(
        f"/api/v1/admin/roles/{role_id}",
        json={"permissions": ["stock.view", "fake.permission"]},
        headers=headers,
    )
    assert unknown.status_code == 422
    assert "fake.permission" in unknown.json()["detail"]["message"]

    listing = await client.get("/api/v1/admin/roles", headers=headers)
    row = next(item for item in listing.json()["data"] if item["id"] == role_id)
    assert set(row["permissions"]) == {"dashboard.view"}


async def test_administrator_role_is_protected(client):
    headers = await admin_headers(client)
    roles = (await client.get("/api/v1/admin/roles", headers=headers)).json()["data"]
    admin = next(role for role in roles if role["name"] == "Administrator")
    assert admin["is_system"] is True
    assert admin["permissions"] == ["ALL_PAGES"]

    strip = await client.patch(
        f"/api/v1/admin/roles/{admin['id']}", json={"permissions": ["report.sales"]}, headers=headers
    )
    assert strip.status_code == 409
    assert "full access" in strip.json()["detail"]["message"].lower()

    rename = await client.patch(
        f"/api/v1/admin/roles/{admin['id']}", json={"name": "Root"}, headers=headers
    )
    assert rename.status_code == 409

    disable = await client.patch(
        f"/api/v1/admin/roles/{admin['id']}", json={"status": "DISABLED"}, headers=headers
    )
    assert disable.status_code == 409

    delete = await client.delete(f"/api/v1/admin/roles/{admin['id']}", headers=headers)
    assert delete.status_code == 409


async def test_role_disable_and_user_reference_guards(client):
    headers = await admin_headers(client)
    role = await _create_role(
        client, headers, name=f"Matrix Locked {uuid.uuid4().hex[:6]}", permissions=["stock.view"]
    )
    role_id = role["id"]

    # Disabling a role with no users is allowed.
    disabled = await client.patch(
        f"/api/v1/admin/roles/{role_id}", json={"status": "DISABLED"}, headers=headers
    )
    assert disabled.status_code == 200

    # A disabled role cannot be assigned to a user.
    assign = await client.post(
        "/api/v1/admin/users",
        json={
            "full_name": "Disabled Role",
            "email": f"disabled-{uuid.uuid4().hex[:8]}@example.com",
            "password": "restricted1",
            "role_id": role_id,
        },
        headers=headers,
    )
    assert assign.status_code == 422

    # Re-activate, assign a user, then deletion is blocked while referenced.
    assert (
        await client.patch(f"/api/v1/admin/roles/{role_id}", json={"status": "ACTIVE"}, headers=headers)
    ).status_code == 200
    holder = await client.post(
        "/api/v1/admin/users",
        json={
            "full_name": "Role Holder",
            "email": f"holder-{uuid.uuid4().hex[:8]}@example.com",
            "password": "restricted1",
            "role_id": role_id,
        },
        headers=headers,
    )
    assert holder.status_code == 201, holder.text
    delete = await client.delete(f"/api/v1/admin/roles/{role_id}", headers=headers)
    assert delete.status_code == 409
    assert "users" in delete.json()["detail"]["message"].lower()


async def test_restricted_roles_enforce_permissions(client):
    headers = await admin_headers(client)

    cashier_role = await _create_role(
        client, headers, name=f"Matrix Cashier {uuid.uuid4().hex[:6]}", permissions=CASHIER_PERMISSIONS
    )
    cashier = await _create_user_headers(client, headers, role_id=cashier_role["id"])

    staff_role = await _create_role(
        client, headers, name=f"Matrix Stock Staff {uuid.uuid4().hex[:6]}", permissions=STOCK_STAFF_PERMISSIONS
    )
    staff = await _create_user_headers(client, headers, role_id=staff_role["id"])

    accountant_role = await _create_role(
        client, headers, name=f"Matrix Accountant {uuid.uuid4().hex[:6]}", permissions=ACCOUNTANT_PERMISSIONS
    )
    accountant = await _create_user_headers(client, headers, role_id=accountant_role["id"])

    missing_id = str(uuid.uuid4())

    # Cashier: read-only POS/stock/dashboard; no administration, products,
    # stock-in or supplier-debt access.
    for path in ("/api/v1/pos/sales", "/api/v1/stock/movements", "/api/v1/dashboard/summary"):
        response = await client.get(path, headers=cashier)
        assert response.status_code == 200, f"cashier GET {path}: {response.status_code}"
    for method, path in (
        ("get", "/api/v1/admin/users"),
        ("post", "/api/v1/stock/in"),
        ("post", f"/api/v1/suppliers/{missing_id}/payments"),
        ("patch", f"/api/v1/products/{missing_id}"),
        ("patch", "/api/v1/admin/settings"),
    ):
        response = await _request(client, method, path, cashier)
        assert response.status_code == 403, f"cashier {method} {path}: {response.status_code}"

    # Stock Staff: stock pages and purchase report; no POS, no administration.
    for path in ("/api/v1/stock/movements", "/api/v1/reports/purchase"):
        response = await client.get(path, headers=staff)
        assert response.status_code == 200, f"staff GET {path}: {response.status_code}"
    for method, path in (
        ("get", "/api/v1/pos/sales"),
        ("post", "/api/v1/pos/sales"),
        ("get", "/api/v1/admin/users"),
        ("get", "/api/v1/admin/settings"),
    ):
        response = await _request(client, method, path, staff)
        assert response.status_code == 403, f"staff {method} {path}: {response.status_code}"

    # Accountant: every report; no settings, user management or POS.
    for path in (
        "/api/v1/reports/sales",
        "/api/v1/reports/finance",
        "/api/v1/reports/customer-debts",
        "/api/v1/reports/supplier-debts",
    ):
        response = await client.get(path, headers=accountant)
        assert response.status_code == 200, f"accountant GET {path}: {response.status_code}"
    for method, path in (
        ("get", "/api/v1/admin/settings"),
        ("get", "/api/v1/admin/users"),
        ("get", "/api/v1/pos/sales"),
    ):
        response = await _request(client, method, path, accountant)
        assert response.status_code == 403, f"accountant {method} {path}: {response.status_code}"
