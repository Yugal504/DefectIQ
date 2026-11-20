# DefectIQ AI Solution

End-to-end defect management consolidated from **GitHub** and a customer
**Smartsheet**, in one project:

- a browser **extraction bot** (GitHub + Smartsheet → Excel), and
- a **FastAPI dashboard + Agentic AI chatbot** that reads the consolidated
  workbook.

Everything runs with **one command** and all configuration lives in a single
`.env` file.

## Quick start

```powershell
# 1. Install dependencies (one-time) into the project venv
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. Edit .env (credentials, repo/sheet URLs, Azure OpenAI, etc.)

# 3. Run everything
.\.venv\Scripts\python.exe main.py
```

Use Python 3.12 for the pinned dependencies. Virtual environments are not
portable between Python versions; recreate `.venv` and reinstall dependencies
when changing interpreters rather than reusing its installed native modules.

`.\.venv\Scripts\python.exe main.py` runs four services in order:

1. **GitHub** – open Edge/Chrome, log in, export issues to CSV.
2. **Smartsheet** – log in, export the sheet to Excel.
3. **Data load** – load both exports into `data/Cockpit_Issue_Tracker.xlsm`
   (the workbook the dashboard reads).
4. **Dashboard** – start the web app and open `http://127.0.0.1:8000`.

Logins pause for you to complete any MFA/SSO in the browser window.

> To start **only the dashboard** (no extraction): `.\.venv\Scripts\python.exe run.py`

## Smartsheet service type

Set one variable in `.env` to select the Smartsheet export interface:

```dotenv
SERVICE_TYPE=org
```

| Value | Export navigation |
|-------|-------------------|
| `org` (default) | File > Export > Export to Microsoft Excel |
| `personal` | More options (three dots) > Export > Microsoft Excel |

This setting selects the menu layout only; it does not switch saved credential
sets or change the GitHub workflow. Set `SMARTSHEET_USERNAME`,
`SMARTSHEET_PASSWORD`, and `SMARTSHEET_SHEET_URL` for the intended account.
Choose the type matching the sheet's actual interface. Both modes wait for the
Excel download before closing the browser and returning to Service 3.

## Reset saved sessions

Before changing credentials, stop the service and close its automation browser.
Update `.env`, then run these commands from the project folder:

```powershell
# Optional: preview without changing any files
.\.venv\Scripts\python.exe clear_sessions.py --dry-run

# Reset saved automation sessions, then start the service
.\.venv\Scripts\python.exe clear_sessions.py
.\.venv\Scripts\python.exe main.py
```

The reset script reads `CHROME_PROFILE_DIR` and `REMOTE_DEBUG_PORT` from the
project `.env`. It renames the entire automation profile to a timestamped sibling
backup instead of deleting it. The next run creates a clean profile and uses
the configured credentials; complete SSO/MFA in the browser when requested.
**Both GitHub and Smartsheet sessions are reset**, including saved account
choices and autofill data in that automation profile. Personal browser profiles,
downloads, and workbooks are not changed. The backup still contains sensitive
session data: keep it private and do not commit it. The script refuses to run
while the configured debugging port is in use. Ensure the service and reset
script use the same profile/port settings; do not override those in the shell.

## Demo accounts (dashboard)

| User | Password | Role |
|------|----------|------|
| `admin` | `admin123` | Administrator (all + delete + audit) |
| `pm` | `pm123` | Project Manager |
| `dev` | `dev123` | Developer |
| `user` | `user123` | Business User |
| `viewer` | `viewer123` | Read-Only |

Demo users live in `.env` (`DEMO_USERS`); replace with SSO/OAuth for production.

## Project layout

```
DefectIQ_AI_Solution/
├─ main.py            # one-command orchestrator (extraction → load → dashboard)
├─ run.py             # start just the dashboard
├─ .env               # single consolidated configuration (no hardcoded values)
├─ requirements.txt   # unified dependencies
├─ script.txt         # approved GitHub export script (repo injected from .env)
├─ app/               # FastAPI dashboard + agentic chatbot
│   ├─ main.py  config.py  auth.py  data_loader.py  reconciliation.py
│   ├─ store.py  reporting.py  models.py
│   ├─ chatbot/        # Agentic AI (tools + Azure OpenAI + offline fallback)
│   └─ service_bot/    # optional live GitHub/Smartsheet API extraction
├─ extraction/        # browser bot (DevTools Protocol, no WebDriver)
│   ├─ github_login.py  smartsheet_login.py  smartsheet_export.py
│   └─ data_load.py
├─ frontend/          # single-page dashboard (HTML/JS + self-hosted Plotly)
├─ data/              # master workbook + overrides + backups (Archive/)
├─ downloads/         # extraction downloads (git-ignored)
└─ logs/              # execution + audit logs
```

## Notes

- **Browser automation is driver-free**: the bot launches installed Edge/Chrome
  with `--remote-debugging-port` and drives it over the Chrome DevTools
  Protocol, so no `chromedriver`/`msedgedriver` is needed (corporate policy
  blocks those).
- **Plotly is self-hosted** (`frontend/vendor/plotly.min.js`, loaded deferred).
  The dashboard no longer depends on an external CDN, which previously stalled
  the sign-in page in managed/corporate Edge.
- The data-load step saves a timestamped backup of the workbook under
  `data/Archive/` before every write. Saving the `.xlsm` via openpyxl rebuilds
  the file and drops pre-built PivotTable sheets (the dashboard computes its own
  charts/KPIs from the raw sheets).
