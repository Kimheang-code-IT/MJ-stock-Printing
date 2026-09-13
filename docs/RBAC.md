# RBAC — Roles & Permissions (as implemented)

## 1. Model

- **Permission** rows are catalog-driven: `module.action` strings synced into the `permissions` table by `build_all_permissions()` (on setup, on `app.seed`, and on Administrator creation). One wildcard: `ALL_PAGES`.
- **Role** 1—N **RolePermission**; users have exactly one role. `roles.is_system` protects the Administrator role (cannot rename, disable, or strip `ALL_PAGES`).
- Effective permissions resolve from the live role (`effective_permissions`); an Administrator with `ALL_PAGES` collapses to the wildcard. Granting any non-view action auto-grants the module's `view` (`normalize_role_permissions`).

## 2. Backend permission catalog (`app/core/permissions.py`)

| Module | Actions |
|---|---|
| dashboard | view, view_profit |
| category / uom / brand | view, create, update, delete |
| stock | view, in, adjust, damage, expire |
| product | create, update, delete |
| supplier | view, create, update, delete, debt.pay |
| pos | access, discount, debt_sale, print |
| customer | view, create, update, delete, debt.pay |
| delivery | view, create, update, confirm, deliver, cancel |
| report | sales, purchase, customer_debt, supplier_debt, finance |
| expense | create (Add Expense on the Finance report only) |
| user / role / sequence | manage |
| audit | view |
| settings | manage |
| service-only (non-assignable) | telegram.reset.send |

## 3. Enforcement points

- Every protected endpoint declares `Depends(require_permission("module.action"))` — see the permission column in [API.md](API.md). `require_permission` chains `get_current_user` (active account + token version) then `user_has_permission` (`ALL_PAGES` or exact code) → 403 `ACCESS_DENIED` otherwise.
- Read endpoints are also permission-gated (e.g. `stock.view`, `report.*`, `audit.view`), so the audit trail and reports are not reachable by bare authentication.
- Object-level checks (IDOR guards): debts must belong to the path customer/supplier; included debts must belong to the sale's customer; delivery notes are only created from real sales; images are path-traversal-guarded; the last active admin cannot be demoted; the walk-in customer cannot take debt.
- The frontend performs the same checks for UX only (`middleware/auth.global.ts`, `useMenu`, disabled buttons) — the backend remains the security boundary.

## 4. Seeded roles

`python -m app.seed` / initial setup create:

- **Administrator** (system): `ALL_PAGES`.
- Preset definitions exist in code for **Cashier** (`cashier_permissions`: dashboard.view, stock.view, pos.access, pos.print, customer.view/create, report.sales) and **Stock Staff** (`stock_staff_permissions`: dashboard/category/brand view, stock.* operations, product create/update, supplier view/create) — used by tests/seeding helpers for realistic non-admin roles.

## 5. ⚠️ Known issue: frontend/backend permission-key drift

The frontend role matrix (`app/utils/role/permissions.ts::ROLE_DOCUMENT_TYPES`) and the route guards (`useMenu`, `definePageMeta`) use **their own permission vocabulary**, which only partially matches the backend catalog:

| Frontend id (page / matrix row) | Backend catalog equivalent | Match? |
|---|---|---|
| `dashboard.view` | dashboard.view | ✅ |
| `categories.view/create/…` | `category.*` | ❌ (plural vs singular) |
| `uom.*`, `brand.*` | uom.*, brand.* | ✅ |
| `products.view/create/edit/delete/export` | `stock.view`, `product.create/update/delete` | ❌ |
| `suppliers.*`, `customers.*` | `supplier.*`, `customer.*` | ❌ (plural) |
| `pos.view`, `pos.print`, `pos.operate`, `pos.export` | `pos.access`, `pos.print`, `pos.discount`, `pos.debt_sale` | ⚠️ only `pos.print` matches |
| `delivery.*` (view/create/update/confirm/deliver/cancel) | delivery.* | ✅ |
| `sales.*`, `reports.*` | `report.sales/purchase/customer_debt/supplier_debt/finance` | ❌ |
| `admin.users.*`, `admin.roles.*`, `admin.audit_logs.*` | `user.manage`, `role.manage`, `audit.view` | ❌ |
| `configuration.*` (document sequences) | `sequence.manage` | ❌ |
| `settings.app_config.*` | `settings.manage` | ❌ |

Consequences observable today:

1. **Menu/page visibility for non-admin roles is unreliable.** `AppRolePermissionMatrix` loads the backend catalog (`GET /admin/permissions`) and keeps only matrix rows whose `permissionPrefix` equals a backend `module`; mismatched rows (categories, products, suppliers, customers, sales, reports, admin.*, configuration, settings.app_config) are filtered out of the matrix and fail closed. Non-`ALL_PAGES` roles therefore cannot be granted — nor see — those areas through the UI, while `useMenu` checks like `products.view` / `pos.view` never match backend codes such as `stock.view` / `pos.access`.
2. **Saving a role from the frontend matrix can be rejected** by the backend (`normalize_role_permissions` → 422 "Unknown permissions") whenever flattened keys include non-catalog codes.
3. Only accounts with `ALL_PAGES` (Administrator) experience full navigation today.

This is a documentation-first finding (no code changed yet). A fix would map matrix rows ↔ catalog codes (or regenerate the matrix from the catalog) and align `useMenu`/`definePageMeta` ids with the backend codes.

## 6. Frontend check flow

```
login → /auth/me (effectivePermissions = backend codes)
  → stores/auth.canAccessPage(id)   # ALL_PAGES or id ∈ permissions
  → middleware auth.global.ts       # definePageMeta({ permission }) per route
  → useMenu filterItem              # sidebar items hidden when denied
  → buttons/actions disabled        # e.g. discount controls without pos.discount
```

Because of §5, a page id like `admin.users.view` is only satisfied by `ALL_PAGES`; granular backend grants (`user.manage`) do not surface in the UI. Backend enforcement is unaffected and remains authoritative.
