# Testing notes for this delivery

This project was built and statically verified in a sandboxed environment **without any network
access** for `pip install`, `docker pull`, or `apt` (only search/fetch tooling had internet access).
That means it was not possible to actually install dependencies, build the Docker image, or run the
app end-to-end before delivering it to you. What *was* done to compensate:

- Every Python file compiles cleanly (`python -m py_compile`).
- Static analysis with `flake8`'s pyflakes checks (`F` codes) across the whole `app/` package came
  back completely clean — no undefined names, no unused imports, no obviously broken references.
- Every Jinja2 template was parsed to confirm there are no template syntax errors.
- Every link/form action/htmx call in every template was manually cross-referenced against the
  actual registered FastAPI routes to make sure nothing points at a nonexistent endpoint.
- The vendored `htmx.min.js` and `alpine.min.js` files were validated with `node -c` (syntax check).
- Model relationships, SQLAlchemy query usage, and enum value handling were manually reviewed line
  by line for correctness (a few real bugs were caught and fixed this way, e.g. an invalid
  `order_by` string expression, and an auth edge case for deleted user sessions).

**What this means for you**: the app should work, but you are effectively the first real
integration test. Please run through this checklist on first boot and let me know if anything
breaks — I can debug quickly from here.

## First-run checklist

```bash
cd personal-crm
cp .env.example .env
docker compose up -d --build
```

There's also an automated smoke test script (`scripts/smoke_test.sh`) that exercises the setup
wizard, login, person creation, and export endpoints via curl - run it against a **brand new**
instance right after `docker compose up`:

```bash
./scripts/smoke_test.sh              # defaults to http://localhost:8000
./scripts/smoke_test.sh http://your-host:8000
```

It will create a real "Smoke Test" admin account and a "Smoke Test Friend" person, so only run it
against a throwaway instance (or delete the test data afterwards). If you'd rather test manually,
or want deeper coverage, walk through this checklist:

1. Open `http://localhost:8000` — you should land on the **setup wizard** (create admin account).
2. Log in, land on the **Today dashboard** (should be empty/friendly, no errors).
3. **Add a person** (People → Add person) — fill in a birthday a few days out to test the birthday
   widget, save, confirm you land on their profile.
4. **Log a journal entry** from their profile (or Quick entry in the sidebar) — confirm it shows up
   on their timeline, and confirm the "quick-add a new person" control works and tags them too.
5. **Settings → Immich**: enter your server URL + API key, click *Test connection*. If it succeeds,
   go to a person's profile and try **Link Immich face** — confirm the picker loads faces and
   photos show up after linking. Check the dashboard's "On this day" card too.
6. **Settings → AI assistant**: enter a base URL/key/model, click *Test connection*. If it works,
   try **Generate summary** and **Suggest things to talk about** on a person's profile, and check
   that a new journal entry produces suggestions to review (small 🤖 link under the entry).
7. **Settings → Instagram**: optional and off by default — only test this with a throwaway account
   per the README's warning.
8. **Review queue**: click *Check now* to manually trigger the daily job (birthday drafts +
   Instagram poll) instead of waiting for the scheduled time.
9. **Export**: download both the JSON and CSV exports and confirm they contain your test data.
10. Restart the container (`docker compose restart`) and confirm you're still logged in and all
    data persisted (tests the SQLite volume + session secret persistence).

## If something breaks

Please share the exact error (container logs via `docker compose logs -f`, and/or the browser
error) and I can patch it directly — most likely culprits given the untested nature of this build
would be a minor template/route mismatch or a dependency version hiccup in `requirements.txt`.
