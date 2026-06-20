# OpenWolf

@.wolf/OPENWOLF.md

This project uses OpenWolf for context management. Read and follow .wolf/OPENWOLF.md every session. Check .wolf/cerebrum.md before generating code. Check .wolf/anatomy.md before reading files.


# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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

> **Gunicorn `--preload`**: `bench clear-cache` alone does NOT reload Python in memory. After any Python change:
> ```bash
> kill -HUP $(pgrep -f "gunicorn.*frappe" | head -1)
> ```

---

## Architecture

### Two codebases in one repo

| Layer | Location | Stack |
|---|---|---|
| Frontend SPA | `POS/src/` | Vue 3 + Vite + Pinia + frappe-ui |
| Frappe app | `pos_next/` | Python + Frappe framework |

The Vue app compiles to `pos_next/public/pos/` and is served as a standalone PWA at `/pos`. It **bypasses** Frappe's `app_include_js` hooks — scripts cannot be injected via hooks.

> **pos_guard.js** (`easy_entry` app): must be present in `pos_next/www/pos.html` before `</body>`. `npm run build` and `bench update` can silently remove it. Always re-check after either operation:
> ```html
> {% if easy_entry_installed %}
> <script src="/assets/easy_entry/js/pos_guard.js"></script>
> {% endif %}
> ```

### Frontend structure

```
POS/src/
├── pages/          # POSSale.vue (main POS page — owns global keyboard handling, dialog orchestration)
├── components/     # sale/, shift/, common/, settings/, invoices/
├── stores/         # Pinia: posCart, itemSearch, customerSearch, posSettings,
│                   #        bootstrap, posShift, posEvents, posOffers, posUI
├── composables/    # useInvoice, useItems, useOffline, useShift, useToast, usePermissions,
│                   #   useSearchInput (barcode/search input state, owns scanner/auto-add toggles)
├── utils/          # Pure JS; offline/ subdirectory for worker helpers
└── workers/        # offline.worker.js — ALL IndexedDB ops run here
```

### Backend structure

```
pos_next/
├── api/            # @frappe.whitelist() endpoints: bootstrap, items, invoices, customers,
│                   #   offers, shifts, wallet, promotions, qz, auth, localization
├── pos_next/doctype/   # 20+ custom doctypes
├── overrides/      # CustomSalesInvoice — wallet GL entries; hooks into on_submit
├── services/       # Business logic (offers engine, stock, sync)
└── tasks/          # Scheduled: branding monitor (hourly), promo cleanup (daily)
```

**Key hook points in `hooks.py`**: `Sales Invoice` validate/submit/cancel (wallet, paid-amount validation), `Customer` after_insert/on_update (Socket.IO broadcast), `POS Profile` on_update (broadcasts to open sessions).

### State flow

`bootstrap` store (single API call on startup) → Pinia stores → components. Cart mutations go through `posCart` store; taxes/totals computed reactively.

---

## Frontend API Patterns

**Vue components (`.vue`)** → `createResource` from `frappe-ui`:
```js
import { createResource } from 'frappe-ui'
const res = createResource({ url: 'pos_next.api.items.get_items', auto: false, onSuccess(d) { ... } })
```

**Composables & stores (`.js` in `src/`)** → `call` from `@/utils/apiWrapper`:
```js
import { call } from '@/utils/apiWrapper'
const result = await call('pos_next.api.items.get_item_details', { item_code, pos_profile })
// result is already unwrapped — no .message needed
```

> Do **not** use `window.frappe.call` in the SPA — it may be unavailable. `@/utils/apiWrapper` wraps frappe-ui's `call` with CSRF auto-refresh.

---

## Translation

Always wrap user-facing strings in `__()`. Variables go as the second argument using `{0}` placeholders; never template literals or string concatenation.

```js
__('Added {0} to cart', [item.item_name])               // ✅
__(`Added ${item.item_name} to cart`)                   // ❌ template literal
__('Added ') + item.item_name + __(' to cart')          // ❌ concatenation
```

For plural forms, write a complete string for each form. For ambiguous words, pass a context string as the third argument: `__('Change', null, 'Coins')`.

---

## Toast Notifications

Use `useToast` composable — never `window.frappe.msgprint` or frappe-ui's `toast`:
```js
const { showSuccess, showError, showWarning } = useToast()
showError(error.message || __('Operation failed'))
```

---

## Item Selection Dialog Pattern

Adding an item that needs user input (variant selection, UOM choice, quantity entry) follows this pattern in `POSSale.vue`:

```js
// 1. Stage the pending item with a mode
cartStore.setPendingItem(item, qty, mode)  // modes: 'variant', 'uom', 'simple', 'cart-edit'
uiStore.showItemSelectionDialog = true

// 2. ItemSelectionDialog emits @option-selected → handleOptionSelected(option)
//    option.type matches the mode; for 'uom'/'simple'/'cart-edit' option.quantity is set
//    'simple'    → cartStore.addItem()           (new item, quantity only dialog)
//    'cart-edit' → cartStore.updateItemQuantity() (existing cart item, quantity only dialog)
//    'uom'       → resolves UOM pricing then addItem()
//    'variant'   → may chain to 'uom' mode
```

Scanner-only mode (scanner ON, auto-add OFF) forces the `'simple'` dialog for every add route.

---

## Global Keyboard Shortcuts

Defined in `POSSale.vue → handleGlobalKeydown`. Shortcuts work from input fields when noted:

| Shortcut | Action |
|---|---|
| F1 (or `?`) | Open Keyboard Shortcuts help dialog (`KeyboardShortcutsDialog.vue`) |
| F4 | Focus item search input |
| F8 | Focus customer search input (temporarily deselects current customer to reveal the input; Escape/outside-click restores via `previousCustomer`) |
| F9 | Proceed to payment |
| Alt+1…5 | Add search result item #N to cart (works from search input) |
| Alt+Q | Open quantity dialog for last cart item (works from search input) |

Payment dialog (own handler `handlePaymentMethodShortcut` in `PaymentDialog.vue`): Alt+1…9 selects payment method #N, **Alt+C** = Pay on Account (credit sale, same guards as the orange button — submits immediately).

Guard: non-F-keys and non-Alt shortcuts are blocked when an `INPUT` or `TEXTAREA` is focused (pos_guard.js idle-refocuses item search, which is why help uses F1, not just `?`). All sale-screen shortcuts are suppressed while any `useDialog`-registered dialog is open (`uiStore.isAnyDialogOpen`). To add a new shortcut that works from inputs, add it to the `isAltDigit`/`isAltQ` guard pattern. Inline `<kbd>` hints use `components/common/KbdHint.vue` (`hidden md:inline-flex`).

---

## Offline / IndexedDB

**All IndexedDB operations must run in the Web Worker** (`src/workers/offline.worker.js`). Main thread communicates via `src/utils/offline/workerClient.js`.

```js
import { offlineWorker } from '@/utils/offline/workerClient'
const items = await offlineWorker.searchCachedItems(term, limit)
```

When querying boolean fields in Dexie, use `.filter()` not `.where().equals()` — booleans are not valid Dexie index keys.

---

## Domain Rules & Pitfalls

**`POS Payment Method` has no `default_account` field.** Get the account from `Mode of Payment Account` table:
```python
mop_account = frappe.db.get_value("Mode of Payment Account", {"parent": mode_of_payment, "company": company}, "default_account")
```

**`Item.valuation_rate` is 0** for most items (ERPNext only populates it for "Standard" valuation method). Priority order for buying cost: `Item Price (buying=1)` → `Bin.valuation_rate` → `Item.valuation_rate`. Implemented in `get_item_detail()` and `get_items()` in `pos_next/api/items.py`.

**Cart item `valuation_rate` may be 0 on add** because item search is cache-first (IndexedDB). `useInvoice.addItem()` fires a background `get_item_details` call when `valuation_rate = 0` and sets the result on the **reactive proxy** (`invoiceItems.value[idx]`), not the original plain object — setting it on the original won't trigger Vue re-render.

**`POS Profile` may not have `customer_group`.** Always use `hasattr()` before accessing it in Python.

**New POS Settings fields MUST be added to `POS_SETTINGS_FIELDS` and `DEFAULT_POS_SETTINGS` in `pos_next/api/constants.py`.** `get_pos_settings` selects `"*"` so the settings dialog sees new fields automatically, but the normal SPA boot path (`pos_next.api.bootstrap.get_initial_data → _get_pos_settings`) uses the `POS_SETTINGS_FIELDS` whitelist — a field missing there silently never reaches the frontend store. Being a Python change, it also needs a gunicorn HUP, not just clear-cache.

**`POS Settings` is a per-POS-Profile doctype, not a Single.** One row per profile in `tabPOS Settings` (queried by `{"pos_profile": ..., "enabled": 1}`); don't use `get_single_value`.

**The frappe-ui Tailwind preset does not generate all color families.** `emerald`, `rose`, `indigo`, `sky`, `lime`, `fuchsia` classes silently produce nothing (invisible elements). Stick to: blue, green, violet, amber, pink, cyan, orange, teal, red, purple, yellow, gray. Verify with `grep -c '\.bg-<color>-100' pos_next/public/pos/assets/index-*.css` after build.

**If /pos serves a blank page with 404s on hashed bundles after a build**, the Redis-cached `pos.html` references old asset hashes — run `bench --site <site> clear-website-cache`.

**`filteredItems` fallback**: when `searchTerm` is set but `searchResults` is empty, the `itemSearch` store falls back to `allItems`. In scanner mode this causes the wrong cached item to be added on Enter. Guard the "add first result" path with `!scannerEnabled.value`.

---

## Feature: Cart Stock & Buying Price Display

Each cart row in `InvoiceCart.vue` shows `N left` (remaining stock) and optionally `Cost: E£ X.XX` (buying price, controlled by `POS Settings → show_buying_price`).

Remaining stock formula (in cart UOM):
```js
Math.max(0, (item.actual_qty ?? 0) / (item.conversion_factor || 1) - (item.quantity ?? 0))
```

`posSettings.canSeeBuyingPrice` reads `show_buying_price` directly from settings (no role gate — the setting itself is the gate).
