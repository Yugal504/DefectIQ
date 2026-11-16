"""FastAPI backend for the Defect Management Agentic AI Solution."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from . import auth, reporting
from .chatbot import DefectAgent
from .config import get_settings
from .models import (
    ChatRequest,
    ChatResponse,
    DefectCreate,
    DefectUpdate,
    LoginRequest,
)
from .store import DefectStore
from .service_bot import ServiceBot, run_extraction

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    store = DefectStore(settings)
    state["settings"] = settings
    state["store"] = store
    state["agent"] = DefectAgent(store)
    bot = ServiceBot(store, settings)
    bot.start()
    state["bot"] = bot
    yield
    bot.stop()


_settings = get_settings()
app = FastAPI(title=_settings.app_title, version=_settings.app_version, lifespan=lifespan)


# ------------------------------------------------------------------ auth deps
def current_user(request: Request) -> dict:
    header = request.headers.get("Authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    payload = auth.verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return payload


def require(permission: str):
    def dep(user: dict = Depends(current_user)) -> dict:
        if not auth.has_permission(user["role"], permission):
            raise HTTPException(status_code=403, detail=f"Missing permission: {permission}")
        return user

    return dep


def get_store() -> DefectStore:
    return state["store"]


# ---------------------------------------------------------------------- auth
@app.post("/api/login")
def login(body: LoginRequest):
    user = auth.authenticate(body.username, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = auth.issue_token(user)
    return {
        "token": token,
        "user": {"username": user["username"], "role": user["role"], "name": user["name"]},
        "permissions": sorted(auth.permissions_for(user["role"])),
    }


@app.get("/api/me")
def me(user: dict = Depends(current_user)):
    return {
        "user": {"username": user["username"], "role": user["role"], "name": user.get("name")},
        "permissions": sorted(auth.permissions_for(user["role"])),
    }


# ---------------------------------------------------------------------- KPIs
@app.get("/api/kpis")
def kpis(user: dict = Depends(require("view"))):
    return get_store().kpis()


@app.get("/api/charts")
def charts(user: dict = Depends(require("view"))):
    from collections import Counter

    defects = get_store().all()

    def norm_priority(p: Optional[str]) -> str:
        if not p:
            return "Unspecified"
        pl = p.lower()
        if "critical" in pl or "urgent" in pl:
            return "Critical/Urgent"
        if "high" in pl:
            return "High"
        if "medium" in pl:
            return "Medium"
        if "low" in pl:
            return "Low"
        return p

    status_c = Counter(d.consolidated_status or "Unknown" for d in defects)
    source_c = Counter(
        ("Linked to GitHub" if d.source_availability == "Both" else "Not Linked")
        for d in defects
    )
    priority_c = Counter(norm_priority(d.priority) for d in defects)
    validation_c = Counter(d.data_validation_status or "Unknown" for d in defects)
    # Open/in-progress defects by owner. Split multi-owner cells (";"/"/"/",")
    # so each person is credited individually, and skip unassigned (it has its
    # own KPI and would otherwise dominate this "by owner" chart).
    import re as _re

    dev_c: Counter = Counter()
    for d in defects:
        if (d.consolidated_status or "").lower() not in {"open", "in progress"}:
            continue
        raw = (d.assigned_developer or "").strip()
        if not raw:
            continue
        for owner in _re.split(r"[;/,]", raw):
            owner = owner.strip()
            if owner:
                dev_c[owner] += 1
    module_c = Counter(d.module or "(none)" for d in defects)
    issue_source_c = Counter(d.issue_source or "(none)" for d in defects)

    return {
        "status_distribution": status_c.most_common(),
        "source_comparison": source_c.most_common(),
        "priority_distribution": priority_c.most_common(),
        "validation_distribution": validation_c.most_common(),
        "developer_distribution": dev_c.most_common(12),
        "module_distribution": module_c.most_common(10),
        "issue_source_distribution": issue_source_c.most_common(12),
    }


# ------------------------------------------------------------------- defects
def _filter_sort(defects, params) -> list:
    search = (params.get("search") or "").strip().lower()
    status = (params.get("status") or "").strip().lower()
    developer = (params.get("developer") or "").strip().lower()
    priority = (params.get("priority") or "").strip().lower()
    source = (params.get("source") or "").strip().lower()
    validation = (params.get("validation") or "").strip().lower()

    def keep(d) -> bool:
        if status and (d.consolidated_status or "").lower() != status:
            return False
        if source and (d.source_availability or "").lower() != source:
            return False
        if validation and (d.data_validation_status or "").lower() != validation:
            return False
        if developer and developer not in (d.assigned_developer or "").lower():
            return False
        if priority and priority not in (d.priority or "").lower():
            return False
        if search:
            hay = " ".join(
                str(x or "")
                for x in (
                    d.defect_title, d.description, d.github_issue_id,
                    d.customer_defect_id, d.assigned_developer, d.module, d.latest_comment,
                )
            ).lower()
            if search not in hay:
                return False
        return True

    rows = [d for d in defects if keep(d)]
    sort_by = params.get("sort") or "last_updated"
    reverse = (params.get("order") or "desc").lower() == "desc"
    rows.sort(key=lambda d: (getattr(d, sort_by, None) is None, str(getattr(d, sort_by, "") or "")), reverse=reverse)
    return rows


@app.get("/api/defects")
def list_defects(
    user: dict = Depends(require("view")),
    search: Optional[str] = None,
    status: Optional[str] = None,
    developer: Optional[str] = None,
    priority: Optional[str] = None,
    source: Optional[str] = None,
    validation: Optional[str] = None,
    sort: str = "last_updated",
    order: str = "desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(_settings.default_page_size, ge=1, le=_settings.max_page_size),
):
    params = dict(search=search, status=status, developer=developer, priority=priority,
                  source=source, validation=validation, sort=sort, order=order)
    rows = _filter_sort(get_store().all(), params)
    total = len(rows)
    start = (page - 1) * page_size
    page_rows = rows[start:start + page_size]
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
        "items": [d.model_dump() for d in page_rows],
    }


@app.get("/api/defects/{record_id}")
def get_defect(record_id: str, user: dict = Depends(require("view"))):
    d = get_store().get(record_id)
    if not d:
        raise HTTPException(status_code=404, detail="Defect not found")
    return d.model_dump()


@app.post("/api/defects", status_code=201)
def create_defect(body: DefectCreate, user: dict = Depends(require("create"))):
    return get_store().create(body, user["username"]).model_dump()


@app.put("/api/defects/{record_id}")
def update_defect(record_id: str, body: DefectUpdate, user: dict = Depends(require("update"))):
    updated = get_store().update(record_id, body, user["username"])
    if not updated:
        raise HTTPException(status_code=404, detail="Defect not found")
    return updated.model_dump()


@app.delete("/api/defects/{record_id}")
def delete_defect(record_id: str, user: dict = Depends(require("delete"))):
    if not get_store().delete(record_id, user["username"]):
        raise HTTPException(status_code=404, detail="Defect not found")
    return {"deleted": record_id}


# ---------------------------------------------------------------------- chat
@app.post("/api/chat", response_model=ChatResponse)
def chat(body: ChatRequest, user: dict = Depends(require("chat"))):
    return state["agent"].answer(body.message, body.history)


# ------------------------------------------------------------------- refresh
@app.post("/api/refresh")
def refresh(user: dict = Depends(require("view"))):
    return run_extraction(get_store(), state["settings"])


# --------------------------------------------------------------------- audit
@app.get("/api/audit")
def audit(user: dict = Depends(require("admin")), limit: int = 200):
    return {"entries": get_store().read_audit(limit)}


# -------------------------------------------------------------------- exports
def _xlsx_response(data: bytes, filename: str) -> Response:
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/export/consolidated")
def export_consolidated(user: dict = Depends(require("download"))):
    data = reporting.build_consolidated_xlsx(get_store().all())
    return _xlsx_response(data, "Consolidated_Issue_Statuses.xlsx")


@app.get("/api/export/filtered")
def export_filtered(
    user: dict = Depends(require("download")),
    search: Optional[str] = None, status: Optional[str] = None,
    developer: Optional[str] = None, priority: Optional[str] = None,
    source: Optional[str] = None, validation: Optional[str] = None,
    sort: str = "last_updated", order: str = "desc",
):
    params = dict(search=search, status=status, developer=developer, priority=priority,
                  source=source, validation=validation, sort=sort, order=order)
    rows = _filter_sort(get_store().all(), params)
    data = reporting.build_consolidated_xlsx(rows, title="Filtered Defects")
    return _xlsx_response(data, "Filtered_Defects.xlsx")


@app.get("/api/export/kpis")
def export_kpis(user: dict = Depends(require("download"))):
    data = reporting.build_kpi_xlsx(get_store().kpis())
    return _xlsx_response(data, "Defect_KPI_Summary.xlsx")


@app.get("/api/export/source/{sheet}")
def export_source(sheet: str, user: dict = Depends(require("download"))):
    mapping = {
        "github": "GitHub Export",
        "smartsheet": "Smart Sheet Export",
        "issue-statuses": "Issue Statuses",
    }
    sheet_name = mapping.get(sheet)
    if not sheet_name:
        raise HTTPException(status_code=404, detail="Unknown sheet")
    data = reporting.extract_source_sheet(state["settings"].workbook_path, sheet_name)
    if data is None:
        raise HTTPException(status_code=404, detail="Sheet not found in workbook")
    return _xlsx_response(data, f"{sheet_name.replace(' ', '_')}.xlsx")


# ------------------------------------------------------------------ frontend
@app.get("/")
def index():
    return FileResponse(
        FRONTEND_DIR / "index.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


class _NoCacheStaticFiles(StaticFiles):
    """Serve static assets with no-cache so the browser always gets the latest."""

    def is_not_modified(self, *args, **kwargs) -> bool:  # noqa: D401
        return False

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response


if FRONTEND_DIR.exists():
    app.mount("/static", _NoCacheStaticFiles(directory=FRONTEND_DIR), name="static")
