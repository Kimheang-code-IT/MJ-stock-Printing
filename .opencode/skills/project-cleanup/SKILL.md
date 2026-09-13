---
name: project-cleanup
description: Use when removing dead code, unused files, duplicates, or obsolete docs from this repository — always before deleting anything.
---

# Project cleanup protocol

**Never delete first.** Deletion is the last step, after classification and approval.

## 1. Search before classifying

For every candidate file, search the **entire repo** for:
- explicit imports/requires and Nuxt auto-imports (components by name + kebab-case, `utils/**` exports, composables)
- route registrations, page configs (`frontend/app/config/*`), menu entries (`useMenu.ts`), middleware redirects
- dynamic/string references, i18n keys, test fixtures, Docker/CI/env references
- backend: router registration in `api/v1/router.py`, model imports, Alembic migrations, tests

Absence of a filename match is **not** proof of dead code — auto-import and string-based wiring hide dependencies.

## 2. Classify every candidate

| Class | Meaning | Action |
|---|---|---|
| KEEP | referenced anywhere, or business-critical, or spec-required | never touch |
| SAFE_REMOVE | zero references found on full search | may remove after user approval |
| REVIEW | ambiguous (dynamics, tests-only, partially used) | report, do not remove |

Present the classification table and wait for approval before removing anything.

## 3. Hard exclusions — never propose removing

- **UOM everywhere** (`/setup/uoms` pages, `uoms` backend module, UOM conversions, migrations 0007/0011) — required by products, stock, POS, pricing, receipts.
- **Delivery Notes** is an approved page with deep integration (POS auto-create, permissions, sequences, migrations 0008/0013/0019/0020, telegram summaries, dashboard KPI). If its removal is ever requested, produce the full dependency list first (pages, components, config, repos, API routes, service, permission set, document sequence, migrations, tests, docs) and get explicit approval.
- Auth/permission plumbing, canonical stock mutation, audit, sequences, migrations history.

## 4. Documentation

`docs/` must contain exactly: `PROJECT.md`, `FRONTEND.md`, `BACKEND.md`, `DATABASE.md`, `BUSINESS_LOGIC.md`, `API.md`. Merge useful content into these files before removing any other doc; never recreate deleted docs.

## 5. After any cleanup

Re-run affected checks (see the `testing` skill), verify no dangling imports, and report: removed / modified / kept / risks.
