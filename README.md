# Daily Tracker

A calendar web app for your daily work log. Your **Google Sheet "Daily"** is the
database: every save in the app is written straight into the month tab (`Nov-26`,
`Dec-26`, …), and anything you type directly in the sheet appears in the app after
**Sync**.

![stack](https://img.shields.io/badge/Flask-3.1-blue) ![storage](https://img.shields.io/badge/storage-Google%20Sheets-34a853) ![deploy](https://img.shields.io/badge/deploy-Render-6c47ff)

## Features

- **Month calendar.** Weekdays, weekends and today, with colour states for Done, In progress, Leave/holiday and Not logged.
- **Several projects per day.** In the day dialog, click **+ Add another project** to log each project with its own category, details, assigned by and status. In the sheet, every project is its own row under the same date, directly below the day's main row, with the day's colours copied. Each calendar cell lists the projects with a status dot, and a strip above the calendar shows how many days you spent on each project that month.
- **One-click log entry.** Project (with autocomplete), task category, details, assigned by and status. Ctrl/Cmd+Enter saves.
- **Google Sheets storage.** Keeps your existing layout: same columns, weekday colours, merged weekend blocks and `MMM-YY` tab names. Missing month tabs are created, styled, when you first log a day in them.
- **Reads legacy tabs** such as `Sept-23` and `June-25`, both MM/DD and DD/MM date text, and rows where the date cell was left blank.
- **Entry templates.** Save entries you log often (e.g. "BnB – development", "Leave"), pick one in the day dialog to fill every field, or save the current day as a template. Templates are stored in a `Templates` tab of your sheet, so you can edit them there too.
- **Bulk apply.** Apply a template to a date range (up to 120 days). Weekends are skipped, and days you've already logged are kept unless you choose *Overwrite*.
- **Month sheet template.** Change the headers, colours (header row plus each weekday), column widths, font, weekend label, spacer rows and weekend merging used for **new** month tabs, with a live preview. Settings are stored in a hidden `_config` tab. Existing tabs are never changed, and *Reset to original* restores the default design.
- **Import history.** Upload an old `.xlsx` workbook (for example `Daily.xlsx` from May–Nov 2026, or the Ellicium history) on the **Import** page. You get a per-month preview first: new days, days that differ from your sheet (shown side by side), identical days, and tabs that will be created. Then pick months and choose whether to keep or replace the differing days. Nothing is written until you confirm. Upload shows a progress bar, and the import itself runs in the background with a live per-month progress page, so you can leave the page while it works.
- **Field journal theme.** Deep forest green with brass accents, Fraunces serif numerals and Manrope text. Both fonts are self-hosted, so there are no third-party requests.
- **Metrics.** Workdays so far, logged, done, in progress, leave, and days not logged yet.
- **CSV export** per month, plus a JSON API at `/api/month/2026-11`.
- **Google sign-in** limited to the email addresses you allow.
- **Production basics.** CSRF protection, a strict CSP, secure cookies, an open-redirect guard, formula-injection-safe writes, retry/backoff on Google API rate limits, a read cache, `/healthz` and `/readyz` endpoints, Docker, CI, and 40+ tests.
- **Mobile layout.** The calendar turns into a day list on phones.

## Architecture

```
Browser ──(Google OAuth)──► Flask app (gunicorn, Render)
                               │  dailytracker/views.py   routes & validation
                               │  dailytracker/model.py   dates, layout, entry rules
                               ▼
                         Storage interface (storage/base.py: caching, upserts)
                          ├── SheetsStorage  → Google Sheets API (service account)  ← production
                          └── ExcelStorage   → local Daily.xlsx                      ← offline / tests
```

## 1. One-time Google setup (about 10 minutes)

Full click-by-click steps are in **[docs/GOOGLE_SETUP.md](docs/GOOGLE_SETUP.md)**. In short:

1. **Google Cloud project.** Enable the *Google Sheets API*.
2. **Service account.** Create one and download its JSON key. Then **share your "Daily" Google Sheet with the service account's `client_email` as Editor.**
3. **OAuth client** (Web application), with redirect URI `https://<your-app>.onrender.com/auth/callback` (and `http://localhost:5000/auth/callback` for local dev).
4. Copy the **Sheet ID** from its URL: `https://docs.google.com/spreadsheets/d/<SHEET_ID>/edit`.

## 2. Deploy on Render

1. Render dashboard → **New → Blueprint** → pick this repo (`render.yaml` is detected).
2. Fill the prompted values:

   | Variable | Value |
   |---|---|
   | `GOOGLE_SHEET_ID` | ID from the sheet URL |
   | `GOOGLE_SERVICE_ACCOUNT_JSON` | the whole service-account JSON (or its base64) |
   | `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | from the OAuth client |
   | `ALLOWED_EMAILS` | your Gmail address (comma-separate several) |

   `SECRET_KEY` is generated for you.
3. Deploy. Add the final `https://….onrender.com/auth/callback` URL to the OAuth client's redirect URIs if you haven't yet.

> The free Render plan sleeps after 15 minutes idle, so the first load after that takes about 30 seconds. Use the Starter plan if you want it always on.

## 3. Import your old Excel history (optional, once)

To bring `Daily Ellicium.xlsx` (Jul 2023 → Apr 2026) and any offline `Daily.xlsx` entries into the Google Sheet:

```bash
cp .env.example .env               # fill GOOGLE_SHEET_ID + GOOGLE_SERVICE_ACCOUNT_JSON
pip install -r requirements-dev.txt
python -m scripts.check_setup      # verifies access to the sheet
python -m scripts.import_excel --history "Daily Ellicium.xlsx" --daily Daily.xlsx --dry-run
python -m scripts.import_excel --history "Daily Ellicium.xlsx" --daily Daily.xlsx
```

Missing month tabs are created and styled. In tabs that already exist, only **empty** days are filled; nothing you've typed is overwritten unless you pass `--overwrite`.

## Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env

# Option A: real Google Sheet (fill the Google vars in .env)
python wsgi.py

# Option B: fully offline against a local workbook, no login
STORAGE_BACKEND=excel EXCEL_PATH=Daily.xlsx AUTH_DISABLED=true python wsgi.py
# → http://localhost:5000
```

Tests and lint:

```bash
pytest
ruff check . && ruff format --check .
```

Docker:

```bash
docker build -t daily-tracker .
docker run --env-file .env -p 8000:8000 daily-tracker
```

## Configuration

All settings are environment variables; see [`.env.example`](.env.example). With `APP_ENV=production` the app refuses to start without a strong `SECRET_KEY`, Google OAuth credentials and `ALLOWED_EMAILS`, and it never allows `AUTH_DISABLED`.

## Endpoints

| Route | Purpose |
|---|---|
| `GET /?month=2026-11` | Calendar (legacy `?sheet=Nov-26` also works) |
| `POST /entry`, `POST /entry/clear` | Save or clear a day (CSRF-protected) |
| `POST /sync` | Drop the cache and re-read the sheet |
| `GET /api/month/2026-11` | JSON for a month (each day lists its project entries) |
| `GET /?day=2026-11-24&project=A&details=…&project=B&details=…` | Quick-add link: opens the day pre-filled (repeat the fields once per project); nothing is saved until **Save** |
| `GET /templates`, `POST /templates/save`, `/templates/delete`, `/templates/apply` | Entry templates and bulk apply |
| `GET /import`, `POST /import/preview`, `GET /import/review/<token>`, `POST /import/run` | Import history from an .xlsx upload |
| `GET /import/progress/<job>`, `GET /import/status/<job>` | Live import progress (page and JSON) |
| `GET /month-template`, `POST /month-template`, `/month-template/reset`, `/month-template/create` | Month sheet template |
| `GET /export/2026-11.csv` | CSV export |
| `GET /healthz`, `GET /readyz` | Liveness, and readiness (checks Google Sheet access) |

## Sheet format

Each month is a tab named `MMM-YY` with columns **Date | Project | Task | Task Details | AssigneBy | Status**. Each day has one row, with a spacer row around each weekend; Saturday and Sunday are merged across C–F. This is the same layout the original `generate_master_excel.py` produced, so your existing sheet works as-is.
