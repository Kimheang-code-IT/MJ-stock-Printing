---
name: testing
description: Use when running, writing, or debugging tests for this repository — pytest (backend), Vitest (frontend), or deciding which checks to run.
---

# Stock & POS testing strategy

Run the **smallest affected area first**, then related areas, then the full suite only when required (task complete, cross-cutting change, or before reporting done).

## Backend — `python -m pytest backend/tests`

Needs the Compose db/redis (host ports 55432 / 56379); `tests/conftest.py` creates `stock_pos_test` and runs all migrations. Suite map and coverage gaps: see `docs/PROJECT.md` §7.

```bash
docker compose up -d db redis
python -m pytest backend/tests/modules/<area> -q   # stock, pos, delivery_notes, reports, auth, administration, telegram…
python -m pytest backend/tests/modules/pos/test_sale.py -q   # single file
python -m pytest backend/tests -q                  # full suite (~4 min)
```

When writing tests: extend the existing area file; reuse fixtures/helpers from `conftest.py` and `tests/utils.py`. Cover rollback, oversell, overpayment, permissions, and sequence concurrency for any transactional change (spec-level rule).

## Frontend — Vitest (`pnpm --dir frontend test`)

Pure unit/adapter tests in `frontend/tests/*.spec.ts` — no browser. Pick the spec matching your change (e.g. `pos-checkout.spec.ts`, `delivery-notes.spec.ts`, `rbac.spec.ts`, `print-documents.spec.ts`).

```bash
pnpm --dir frontend test -- <file>.spec.ts
pnpm --dir frontend typecheck && pnpm --dir frontend lint
pnpm --dir frontend test              # all
pnpm --dir frontend build             # only before reporting a frontend task done
```

## Infrastructure

```bash
docker compose -f docker-compose.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.prod.yml config --quiet
```

Never report a check as passing unless you ran it and saw it succeed.
