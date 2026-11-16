# Defect Management – Agentic AI Solution

An end-to-end implementation of the BRD: a Python Service Bot, a reconciliation
engine, an Agentic AI chatbot, and a professional web dashboard for managing
software defects consolidated from **GitHub** and a customer **Smartsheet**.

The MVP uses the existing Excel workbook
(`data/Cockpit_Issue_Tracker.xlsm`) as its data source and reconciles the
`GitHub Export` and `Smart Sheet Export` worksheets on the **SmartSheet Action
ID** join key.

---

## Quick start

```powershell
# 1. Install dependencies (one-time)
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. (Optional) configure Azure OpenAI + settings
Copy-Item .env.example .env   # then edit .env

# 3. Run
.\.venv\Scripts\python.exe run.py
```

Open http://127.0.0.1:8000 and sign in with a demo account.

| User     | Password     | Role             | Capabilities                          |
|----------|--------------|------------------|---------------------------------------|
| `admin`  | `admin123`   | Administrator    | Everything incl. delete + audit log   |
| `pm`     | `pm123`      | Project Manager  | View, update, download, chat          |
| `dev`    | `dev123`     | Developer        | View, update, download, chat          |
| `user`   | `user123`    | Business User    | View, download, chat                  |
| `viewer` | `viewer123`  | Read-Only User   | View only                             |

> Demo accounts live in `app/auth.py`. Replace with Enterprise SSO / OAuth 2.0
> for production (BD-08).

---

## Architecture (maps to the 4 BRD modules)

```
app/
  config.py                 Settings from env / .env
  data_loader.py            Module 1: read GitHub Export + Smart Sheet Export
  reconciliation.py         Module 2: consolidate on SmartSheet Action ID
  store.py                  Consolidated store: CRUD, overrides, KPIs, audit
  auth.py                   Role-based access control
  reporting.py              Excel / report exports
  chatbot/                  Module 3: Agentic AI
    tools.py                Grounded analytics tools (+ function schemas)
    agent.py                Azure OpenAI function-calling + offline fallback
    nl_fallback.py          Deterministic NL router (works with no LLM)
  service_bot/              Module 1: extraction + scheduler
    github_extractor.py     Live GitHub REST extraction (optional)
    smartsheet_extractor.py Live Smartsheet extraction (optional)
    runner.py               Orchestration, write-back, scheduling
  main.py                   Module 4: FastAPI API + serves the dashboard
frontend/                   Single-page dashboard (HTML/JS + Plotly, no build)
```

### Reconciliation logic
Each GitHub issue is joined to a Smartsheet row via its **SmartSheet Action ID**
(falling back to the `[PROD - ###]` id embedded in the title). Every defect gets:
- **Source Availability** – `Both`, `GitHub`, or `Smartsheet`
- **Consolidated Status** – normalized `Open` / `In Progress` / `Closed`
- **Data Validation Status** – `Matched` / `Missing` / `Duplicate` / `Requires Review`

### Agentic AI chatbot
All answers are **grounded in the consolidated dataset** – the LLM only calls
analytics tools and phrases the result, so it never invents defect facts. With
no Azure OpenAI credentials it automatically runs a deterministic rule-based
engine, so the assistant always works.

To enable the LLM, set in `.env`:
```
AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com
AZURE_OPENAI_API_KEY=<key>
AZURE_OPENAI_DEPLOYMENT=<deployment-name>
```

---

## Data refresh & the Service Bot
- **Manual refresh:** the ⟳ button (or `POST /api/refresh`) re-reads the
  workbook and re-reconciles.
- **Scheduled refresh:** set `SERVICE_BOT_INTERVAL_MINUTES` > 0.
- **Live extraction (optional):** set the `GITHUB_*` / `SMARTSHEET_*` vars to
  pull fresh data from the APIs and write it back into the workbook before
  reconciling. Off by default (Excel is the source of truth for the MVP).

CRUD edits are stored as overlays in `data/defect_overrides.json`, so a refresh
never discards manual changes (BD-05: tracker-only write-back for now).

---

## Key API endpoints
| Method | Path | Permission |
|--------|------|-----------|
| POST | `/api/login` | – |
| GET  | `/api/kpis`, `/api/charts` | view |
| GET  | `/api/defects` (search/filter/sort/paginate) | view |
| GET  | `/api/defects/{id}` | view |
| POST | `/api/defects` | create |
| PUT  | `/api/defects/{id}` | update |
| DELETE | `/api/defects/{id}` | delete |
| POST | `/api/chat` | chat |
| POST | `/api/refresh` | view |
| GET  | `/api/export/{consolidated,filtered,kpis}` | download |
| GET  | `/api/export/source/{github,smartsheet,issue-statuses}` | download |
| GET  | `/api/audit` | admin |

## Tests
```powershell
.\.venv\Scripts\python.exe smoke_test.py
```
Covers auth, RBAC, KPIs, charts, filtered listing, chatbot, full CRUD, exports,
and the audit log against the real workbook.

## Logs
- `logs/execution.log` – Service Bot / refresh runs (BRD 5.1.4)
- `logs/audit.log` – user CRUD actions (NFR: auditability)
