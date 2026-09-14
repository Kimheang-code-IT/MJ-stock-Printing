---
name: database
description: Use when changing database schema, models, migrations, or data integrity rules — SQLAlchemy models, Alembic revisions, constraints, sequences.
---

# Stock & POS database

Read `docs/DATABASE.md` first. Open `docs/BUSINESS_LOGIC.md` when the schema change affects stock/debt/finance/sequence rules.

## Rules

- **Preserve migration history.** Never edit an applied migration under `backend/alembic/versions/`. Every schema change = one new Alembic revision with a correct `down_revision` chain. Never edit a production database by hand.
- Match existing model conventions: UUID PKs, `DateTime(timezone=True)` with `server_default=func.now()`, money `NUMERIC(18,2)`, quantities `NUMERIC(18,4)`, UOM factors/rates `NUMERIC(18,6)`.
- Integrity invariants to preserve (some are DB constraints, e.g. batch quantities in `0024_batch_integrity`):
  - `stock_balances` written only by `apply_stock_movement` under `SELECT … FOR UPDATE`.
  - `stock_movements`, `payments`, `audit_logs` are append-only.
  - Exactly one POS-active sale-price row per product (partial unique index).
  - Document sequences are row-locked and gap-free per allocation (`shared/documents/`).
  - Debts inherit the source document's currency; KHR/USD are never mixed.
- UOM tables (`units_of_measure`) are referenced by products with `RESTRICT` — never drop, rename, or weaken UOM constraints.
- PostgreSQL is authoritative; Redis is transient only. Images live on local disk (`LOCAL_STORAGE_DIR`), keys in PostgreSQL.

## Checks

```bash
docker compose -f infrastructure/docker-compose.yml up -d db redis
cd backend && alembic upgrade head           # applies cleanly on the dev/test DB
python -m pytest backend/tests -q            # conftest migrates a fresh test DB — run areas you touched first
```
