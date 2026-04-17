# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **Frontend-specific rules** (API patterns, translation, offline, component conventions) live in `POS/.claude.md` — that file is authoritative for anything inside `POS/src/`.

---

## Commands

All frontend commands run from `POS/`:

```bash
npm run build          # Production build → pos_next/public/pos/
npm run dev            # Vite dev server (proxies to Frappe backend)
npm run lint           # Biome linter
npm run lint:fix       # Auto-fix lint issues
npm run test:run       # Run tests once (Vitest)
npm run test           # Watch mode
npm run test:coverage  # Coverage report
```

Backend changes take effect after:
```bash
bench --site <site> migrate          # After schema/doctype changes
bench --site <site> clear-cache      # After Python changes
bench build --app pos_next           # Rebuild assets via bench (alternative to npm)
```

---

## Architecture

### Two codebases in one repo

| Layer | Location | Stack |
|---|---|---|
| Frontend SPA | `POS/src/` | Vue 3 + Vite + Pinia + frappe-ui |
| Frappe app | `pos_next/` | Python + Frappe framework |

The Vue app is compiled to `pos_next/public/pos/` and served as a standalone PWA at `/pos`. It **bypasses** Frappe's normal `app_include_js` hooks — so injecting scripts requires editing `pos_next/www/pos.html` (or the compiled `pos_next/public/pos/index.html`) directly.

> **pos_guard.js** (from `easy_entry`): must be manually present in `pos_next/www/pos.html` just before `</body>`:
> ```html
> {% if easy_entry_installed %}
> <script src="/assets/easy_entry/js/pos_guard.js"></script>
> {% endif %}
> ```
> `bench update` or `npm run build` can overwrite `pos.html` and silently remove this. Always re-check after either operation.

### Frontend structure

```
POS/src/
├── pages/          # Entry points: POSSale.vue (main POS), Login, Home
├── components/     # Feature components: sale/, shift/, common/, settings/, invoices/
├── stores/         # Pinia: posCart, itemSearch, customerSearch, posSettings,
│                   #        bootstrap, posShift, posEvents, posOffers
├── composables/    # useInvoice, useItems, useOffline, useShift, useToast, usePermissions
├── utils/          # Pure JS utilities; offline/ subdirectory for worker helpers
└── workers/        # offline.worker.js — ALL IndexedDB ops run here, not main thread
```

**State flow**: `bootstrap` store (single API call on startup) → Pinia stores → components. Cart mutations go through `posCart` store; side-effects (taxes, totals) are computed reactively.

**Offline**: Web Worker (`offline.worker.js`) owns all IndexedDB/Dexie operations. Main thread talks to it via `utils/offline/workerClient.js`. Never access IndexedDB from the main thread.

### Backend structure

```
pos_next/
├── api/            # @frappe.whitelist() endpoints: bootstrap, invoices, items,
│                   #   customers, offers, shifts, wallet, promotions, qz
├── pos_next/doctype/   # 20+ custom doctypes (POS Settings, Wallet, POS Offer, etc.)
├── overrides/      # CustomSalesInvoice — fixes wallet GL entries; hooks into on_submit
├── services/       # Business logic (offers engine, stock, sync)
├── tasks/          # Scheduled: branding monitor (hourly), promo cleanup (daily)
├── report/         # Custom reports (sales_vs_shifts, cashier_performance)
└── hooks.py        # Doc events, override classes, fixtures, scheduled tasks
```

**Key hook points in `hooks.py`**:
- `Sales Invoice` → `validate`, `on_submit`, `on_cancel` (wallet deduction, paid-amount validation)
- `Customer` → `after_insert`, `on_update` (real-time Socket.IO event to all POS terminals)
- `POS Profile` → `on_update` (broadcasts profile change to open sessions)
- Override class: `pos_next.overrides.sales_invoice.CustomSalesInvoice`

### API communication

Frontend → Backend uses two patterns depending on file type (see `POS/.claude.md`):
- Vue components: `createResource` from frappe-ui
- JS utilities: `window.frappe.call`

All backend endpoints are in `pos_next/api/` and decorated with `@frappe.whitelist()`.

Real-time updates use Socket.IO via the `posEvents` Pinia store (lazy connection). Events: `stock_update`, `customer_update`, `pos_profile_updated`.

### Invoice submission flow

`PaymentDialog.vue` → emits `payment-completed` → `useInvoice` composable → `submit_invoice` API → `pos_next/api/invoices.py` → ERPNext `Sales Invoice` submit with `CustomSalesInvoice` override. A coalescing mutex in `useInvoice` prevents duplicate submissions from rapid clicks. When offline, the invoice is queued to IndexedDB via the worker and synced when connectivity resumes.

---

## Key domain rules

- **Payment methods**: `POS Payment Method` child table has no `default_account` field. Get the account from `Mode of Payment Account` table instead.
- **Credit sale** (`is_credit_sale: true`): sends `payments: []` to backend. ERPNext requires at least one payment mode — only works if the site has credit sale support configured.
- **Exact amount mode**: when active for non-cash methods, only the exact invoice total is accepted.
- **Wallet payments**: handled by `CustomSalesInvoice` override which posts correct GL entries to Receivable accounts (not the wallet account directly).
