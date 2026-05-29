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

> **Gunicorn `--preload` warning**: The server runs with `--preload`, so Python workers fork from a preloaded master. After any Python file change, the old code stays in memory until workers are reloaded:
> ```bash
> kill -HUP $(pgrep -f "gunicorn.*frappe" | head -1)   # graceful reload
> ```
> `bench clear-cache` alone is NOT sufficient — it clears Redis but not in-process memory.

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

---

## Feature: Show Buying Price & Remaining Stock in Cart

Each cart item row in `InvoiceCart.vue` shows two extra data points below the item line:

| Element | Visible to | Condition |
|---|---|---|
| `N left` (stock remaining) | Everyone | `item.actual_qty !== undefined` |
| `Cost: E£ X.XX` (buying price) | Everyone when setting ON | `posSettings.show_buying_price = 1` AND `item.valuation_rate > 0` |

### How `show_buying_price` works

Enabled via **POS Settings → Show Buying Price to Authorized Users** toggle. When ON, all cashiers see the cost. The toggle lives in `POS Settings` doctype (`show_buying_price` Check field).

- `posSettings.canSeeBuyingPrice` computed = `Boolean(settings.value.show_buying_price)` — no role gate, purely the setting.
- Previously this was role-gated (`System Manager` / `Nexus POS Manager`) but was removed because the setting itself acts as the gate.

### How `valuation_rate` is sourced (priority order)

`Item.valuation_rate` is 0 for most items. The actual cost is in the `Item Price` or `Bin` table. Priority:

1. **`Item Price`** where `buying = 1` (Standard Buying price list)
2. **`Bin.valuation_rate`** for the item's warehouse (moving average / FIFO cost)
3. **`Item.valuation_rate`** (rarely populated, only for Standard valuation method)

This logic runs in two places:
- `get_items()` in `pos_next/api/items.py` — batch query builds `buying_price_map` and `valuation_rate_map` for search results
- `get_item_detail()` in `pos_next/api/items.py` — single-item lookup used by `get_item_details` endpoint

### Why items may briefly show no cost (cache-first search)

Item searches use a **cache-first** strategy (IndexedDB → server). If the user clicks an item before the server results arrive, the cached item may have `valuation_rate = 0` (old cache). To handle this:

`useInvoice.addItem()` detects `valuation_rate = 0` on a newly added stock item and fires a background call to `pos_next.api.items.get_item_details`. When the response arrives, it sets `cartItem.valuation_rate` on the **reactive proxy** (not the original plain object) to trigger re-render.

### Remaining stock formula

```js
Math.max(0, (item.actual_qty ?? 0) / (item.conversion_factor || 1) - (item.quantity ?? 0))
```

`actual_qty` = warehouse stock in **stock UOM**. `conversion_factor` = stock units per 1 cart UOM unit. `quantity` = qty in cart (cart UOM). Dividing `actual_qty` by `conversion_factor` converts it to cart UOM before subtracting. Note: `item.quantity` (not `item.qty`) is the Pinia cart field name.

### Files changed

| File | Change |
|---|---|
| `pos_next/pos_next/doctype/pos_settings/pos_settings.json` | Added `show_buying_price` Check field |
| `pos_next/api/constants.py` | Added `show_buying_price` to `POS_SETTINGS_FIELDS` and `DEFAULT_POS_SETTINGS` |
| `pos_next/api/bootstrap.py` | `can_see_buying_price` top-level flag (no role gate now) |
| `pos_next/pos_next/doctype/pos_settings/pos_settings.py` | `get_pos_settings()` injects `can_see_buying_price`; buying price priority logic |
| `pos_next/api/items.py` | `get_items()` builds `buying_price_map` + `valuation_rate_map` from Bin; `get_item_detail()` has Item Price → Bin → Item fallback |
| `POS/src/stores/bootstrap.js` | `getCanSeeBuyingPrice()` helper reads top-level `can_see_buying_price` |
| `POS/src/stores/posSettings.js` | `canSeeBuyingPrice` computed reads `show_buying_price` directly; bootstrap optimization fix copies `can_see_buying_price` |
| `POS/src/components/settings/POSSettings.vue` | Checkbox for `show_buying_price` in Display Settings |
| `POS/src/components/sale/InvoiceCart.vue` | Stock & Cost info row rendered under each cart item |
| `POS/src/composables/useInvoice.js` | `resolveUomPricing` returns `valuation_rate`; background fetch on `valuation_rate=0` |
| `POS/src/pages/POSSale.vue` | UOM `itemToAdd` spreads `valuation_rate` from pricing response |

### Service worker & deployment note

The POS is a PWA. After `npm run build`, the new `sw.js` has `skipWaiting()` + `clientsClaim()` so it activates immediately on next page load. Users on an old cached version need `Ctrl+Shift+R` (hard refresh) to bypass the service worker and load new JS.
