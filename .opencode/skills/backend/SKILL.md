---
name: backend
description: Use when working on the FastAPI backend — modules, services, repositories, routers, auth, permissions, stock/POS/debt logic in backend/app/.
---

# Stock & POS backend

Read `docs/BACKEND.md` first. Open `docs/API.md` when touching any endpoint (contract, permission, envelope). Open `docs/BUSINESS_LOGIC.md` before changing money, stock, debt, sale/return, or sequence math. Open `docs/DATABASE.md` only if the change involves models/schema.

## Architecture rules (enforced — do not break)

- Thin routers; transactions and business rules in `app/modules/<m>/service.py`; queries in `repository.py`.
- **One canonical stock mutation**: `stock/service.py::apply_stock_movement` — every stock change goes through it. Never write `stock_balances` from CRUD endpoints.
- Payments, movements, audit rows are immutable/append-only. Debt settlement locks the debt row and rejects overpayment — never "simplify" this.
- Document numbers come from `shared/documents/service.py::allocate_document_number` (row-locked, in the caller's transaction).
- Auth: `require_permission("module.action")` on every protected endpoint; IDOR guards (debt belongs to path party, delivery notes from real sales, walk-in cannot take debt). Never weaken these.
- Errors use the shared envelope + stable codes (`core/errors.py`); audit rows commit inside the business transaction (`record_audit`, never commits alone).
- `NUMERIC` + `Decimal` for money/quantities — never float. Timestamps UTC.

## Before writing code

1. Search for an existing service/repository/helper before creating one — modules: auth, administration, categories, uoms, brands, stock, suppliers, customers, pos, delivery_notes, dashboard, reports, image, telegram.
2. Do not add new modules, endpoints, or dependencies outside the approved surface in `AGENTS.md`.
3. `core/scheduler.py` runs expiry alerts in-process — do not add Celery beat or scheduler containers.

## Checks (targeted first)

```bash
docker compose up -d db redis                # tests need ports 55432/56379
python -m pytest backend/tests/modules/<area> -q   # affected area only
python -m pytest backend/tests -q            # full suite only when required
python -m ruff check app
```
