# AGENTS.md

## Cursor Cloud specific instructions

### What this is
A single Flask app — a Greek-language "Fire Safety Dashboard" backed by a hosted Supabase
project. There is no separate frontend build (templates + static assets only) and no Node
toolchain. The Flask entrypoint is `App_test.py` (not `app.py`).

### Services / how to run
- Dependencies live in a virtualenv at `.venv` (gitignored). The startup update script
  creates it and installs `requirements.txt`.
- Run the dev server: `.venv/bin/python App_test.py` — serves on `0.0.0.0:5000`.
  Debug mode is off but `TEMPLATES_AUTO_RELOAD` is on, so template edits are picked up live;
  Python code changes require a manual restart.
- Lint/tests: there is no configured linter and there is no automated test suite despite the
  `App_test.py` filename (it is the application, not a test file).

### Supabase / data (important, non-obvious)
- `DatabaseScript.py` connects to Supabase **at import time** and runs a probe query, so any
  process that imports it (the app, `seed_database.py`) needs outbound network access to the
  hosted Supabase URL. Default public URL + publishable anon key are hardcoded as fallbacks,
  so it works with no env vars in this environment.
- Override with env vars when needed: `SUPABASE_URL`, `SUPABASE_KEY` /
  `SUPABASE_SERVICE_ROLE_KEY` / `SUPABASE_ANON_KEY`. SSL fallbacks: `SUPABASE_SSL_VERIFY=false`
  or `SUPABASE_CA_BUNDLE=<path>`.
- The anon key is read-only (RLS): writes (e.g. `seed_database.py`) are blocked and must be
  applied via the SQL files in `Database/` in the Supabase SQL editor. Do not rely on being
  able to seed/write from the app.
- Seed data is static (timestamps from May 2025), so any "freshness/staleness" logic must be
  data-driven rather than wall-clock based.

### App behavior notes
- `/` redirects to `/login`. Login has no password: you pick a fire region, which is stored in
  the session. The headquarters option `Αρχηγείο / Ε.Σ.Κ.Ε.ΔΙ.Κ.` sees all regions.
- Admin panel: on the login page expand "Πρόσβαση Διαχειριστή" and enter the admin code
  (default `123`, override with `ADMIN_PANEL_CODE`) to reach `/admin`, which shows DB health,
  node message stats, and parent-node report stats. JSON at `/api/admin/stats`.
- Drone telemetry (`/api/drones`, `/drone`) is simulated in-memory by `drone_sim.py`; it falls
  back to mock drones if the DB table is missing/empty.
