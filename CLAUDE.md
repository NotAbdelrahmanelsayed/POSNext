# OpenWolf

@.wolf/OPENWOLF.md

This project uses OpenWolf for context management. Read and follow .wolf/OPENWOLF.md every session. Check .wolf/cerebrum.md before generating code. Check .wolf/anatomy.md before reading files.

# Production Verification (MANDATORY before declaring work done)

Testing against the vite dev server (even proxied to the live backend) is NOT sufficient to call a change "verified" — the real site at `https://erp.abderlahman-erp.store` serves the static build in `pos_next/public/pos/`, which only updates after an explicit build + cache clear. A change can pass every dev-server check and still be invisible in production.

Before telling the user a frontend or backend change is done:

1. **Frontend changes:** run `npm run build` in `POS/`, then `bench --site erp.abderlahman-erp.store clear-cache`. Confirm the new build is live by checking `https://erp.abderlahman-erp.store/assets/pos_next/pos/version.json` — its timestamp must be newer than your last source edit.
2. **Verify against the real production URL** (`https://erp.abderlahman-erp.store`, not `127.0.0.1:8000` or the vite dev server) using whichever tool fits the change:
   - UI-visible changes: `/frappe-visual-reviewer` or a scripted Playwright check (see `.wolf/OPENWOLF.md` / prior session notes for the login + screenshot pattern) — actually see the element/behavior render on the production page.
   - Backend-only changes (API endpoints, server logic): call the endpoint directly against the production site (`bench --site erp.abderlahman-erp.store console`, or an authenticated HTTP request) and inspect the real response/output.
3. Only report the task as shipped after this production-level check passes. A dev-server pass alone is not "verified" — say so explicitly if you weren't able to complete the production check.

See `.wolf/buglog.json` (bug-035) for a prior incident where a feature looked broken to the user because the production build was stale, despite dev-server QC passing.
