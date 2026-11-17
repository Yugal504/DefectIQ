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
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. Edit .env (credentials, repo/sheet URLs, Azure OpenAI, etc.)

# 3. Run everything
python main.py
```

`python main.py` runs four services in order:

1. **GitHub** – open Edge/Chrome, log in, export issues to CSV.
2. **Smartsheet** – log in, export the sheet to Excel.
3. **Data load** – load both exports into `data/Cockpit_Issue_Tracker.xlsm`
   (the workbook the dashboard reads).
4. **Dashboard** – start the web app and open `http://127.0.0.1:8000`.

Logins pause for you to complete any MFA/SSO in the browser window.

> To start **only the dashboard** (no extraction): `.\.venv\Scripts\python.exe run.py`

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
