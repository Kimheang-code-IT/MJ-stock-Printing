---
name: frontend
description: Use when working on the Nuxt frontend — pages, components, composables, stores, i18n, printing, POS UI, module configs, or frontend permissions in frontend/.
---

# Stock & POS frontend

Read `docs/FRONTEND.md` first. Open `docs/API.md` only when you need an endpoint contract (paths, query params, payload shape, permissions).

## Before writing code

1. Find the existing pattern: most CRUD pages are **configuration, not markup** — check `frontend/app/config/*-modules.ts` (`modules.ts`, `stock-modules.ts`, `admin-modules.ts`, `delivery-modules.ts`) rendered by `ModulePage`/`WorkspaceView`/`DocumentView` before building any custom page.
2. Reuse field widgets (`components/common/App*`), tables (`AppListTable`, `AppLineTable`), dialogs, and composables (`useApi`, `useAuth`, `useMenu`, `useAppHeader`, `useModule`). Never create a parallel component that duplicates one.
3. Shared types live in `app/types/stock-pos/`; API constants in `app/utils/constants/api-endpoints.ts` (the only endpoint registry).
4. Keep user-facing strings in `i18n/locales/en.json` + `km.json` (or `labelKm` in module configs).
5. Sidebar/page structure is fixed by `AGENTS.md` — no new routes or menu entries without explicit approval. Do not remove UOM pages.

## Constraints

- Preserve session/auth flow (`utils/auth/`, single-flight refresh in `useApi`), permission checks (`canAccessPage`, `definePageMeta`), and print utilities (`utils/print/`) unless asked.
- Frontend permission checks are UX only — the backend is the security boundary. Known permission-id drift: see `docs/BACKEND.md` §8; do not re-map ids without approval.

## Checks (targeted first)

```bash
pnpm --dir frontend test -- <file>.spec.ts   # affected spec only
pnpm --dir frontend typecheck
pnpm --dir frontend lint
pnpm --dir frontend build                    # only when needed (slow)
```
