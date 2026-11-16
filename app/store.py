"""In-memory consolidated defect store with CRUD, overrides and audit.

The base dataset is derived from the Excel workbook via the reconciliation
engine. CRUD operations are layered on top as persisted "overrides" so that a
workbook refresh never loses manual edits. This implements the BRD decision
BD-05: CRUD updates the consolidated tracker (source write-back is a later,
separately-approved phase).
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from typing import Any, Optional

from .config import Settings, get_settings
from .data_loader import load_workbook_data
from .models import ConsolidatedDefect, DefectCreate, DefectUpdate
from .reconciliation import reconcile, reconciliation_meta

OPEN_STATES = {"open", "in progress"}


class DefectStore:
    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()
        self._lock = threading.RLock()
        self._base: list[ConsolidatedDefect] = []
        self._overrides: dict[str, Any] = {"updates": {}, "deleted": [], "created": []}
        self._meta: dict = {}
        self.last_refreshed: Optional[str] = None
        self.reconciled_at: Optional[str] = None
        self._load_overrides()
        self.refresh()

    # ----------------------------------------------------------------- refresh
    def refresh(self) -> dict:
        """Reload the workbook, reconcile, and log the execution."""
        with self._lock:
            data = load_workbook_data(self.settings.workbook_path)
            self._base = reconcile(data, self.settings.github_repo)
            self._meta = reconciliation_meta(data, self._base)
            self.last_refreshed = data.last_refreshed
            self.reconciled_at = datetime.now().isoformat(sep=" ", timespec="seconds")
            result = {
                "github_rows": len(data.github_rows),
                "smartsheet_rows": len(data.smartsheet_rows),
                "issue_status_rows": len(data.issue_status_rows),
                "consolidated": len(self._base),
                "last_refreshed": self.last_refreshed,
                "reconciled_at": self.reconciled_at,
            }
        self._log_execution(f"REFRESH ok {result}")
        return result

    # ------------------------------------------------------------- effective set
    def _effective(self) -> list[ConsolidatedDefect]:
        """Apply overrides (deletes, updates, created) onto the base set."""
        deleted = set(self._overrides["deleted"])
        updates = self._overrides["updates"]
        out: list[ConsolidatedDefect] = []
        for rec in self._base:
            if rec.record_id in deleted:
                continue
            if rec.record_id in updates:
                merged = rec.model_copy(update=updates[rec.record_id])
                merged.is_overridden = True
                out.append(merged)
            else:
                out.append(rec)
        for created in self._overrides["created"]:
            if created["record_id"] in deleted:
                continue
            out.append(ConsolidatedDefect(**created))
        return out

    def all(self) -> list[ConsolidatedDefect]:
        with self._lock:
            return self._effective()

    def get(self, record_id: str) -> Optional[ConsolidatedDefect]:
        for rec in self.all():
            if rec.record_id == record_id:
                return rec
        return None

    # --------------------------------------------------------------------- CRUD
    def create(self, payload: DefectCreate, user: str) -> ConsolidatedDefect:
        with self._lock:
            rid = f"MAN-{uuid.uuid4().hex[:8]}"
            source = "Both"
            if payload.github_issue_id and not payload.customer_defect_id:
                source = "GitHub"
            elif payload.customer_defect_id and not payload.github_issue_id:
                source = "Smartsheet"
            elif not payload.github_issue_id and not payload.customer_defect_id:
                source = "Manual"
            now = datetime.now().isoformat(sep=" ", timespec="seconds")
            rec = ConsolidatedDefect(
                record_id=rid,
                customer_defect_id=payload.customer_defect_id,
                github_issue_id=payload.github_issue_id,
                defect_title=payload.defect_title,
                description=payload.description,
                consolidated_status=payload.consolidated_status,
                assigned_developer=payload.assigned_developer,
                priority=payload.priority,
                module=payload.module,
                created_date=now,
                last_updated=now,
                source_availability=source,
                data_validation_status="Requires Review",
                github_url=(
                    f"https://github.com/{self.settings.github_repo}/issues/{payload.github_issue_id}"
                    if payload.github_issue_id
                    else None
                ),
                is_manual=True,
            )
            self._overrides["created"].append(rec.model_dump())
            self._save_overrides()
        self._audit(user, "CREATE", rid, {"title": payload.defect_title})
        return rec

    def update(self, record_id: str, payload: DefectUpdate, user: str) -> Optional[ConsolidatedDefect]:
        changes = {k: v for k, v in payload.model_dump().items() if v is not None}
        if not changes:
            return self.get(record_id)
        with self._lock:
            changes["last_updated"] = datetime.now().isoformat(sep=" ", timespec="seconds")
            # Manual (created) records are edited in place.
            for c in self._overrides["created"]:
                if c["record_id"] == record_id:
                    c.update(changes)
                    c["is_overridden"] = True
                    self._save_overrides()
                    self._audit(user, "UPDATE", record_id, changes)
                    return ConsolidatedDefect(**c)
            # Extracted records get an override entry.
            if not any(r.record_id == record_id for r in self._base):
                return None
            self._overrides["updates"].setdefault(record_id, {}).update(changes)
            self._save_overrides()
        self._audit(user, "UPDATE", record_id, changes)
        return self.get(record_id)

    def delete(self, record_id: str, user: str) -> bool:
        with self._lock:
            if not any(r.record_id == record_id for r in self.all()):
                return False
            if record_id not in self._overrides["deleted"]:
                self._overrides["deleted"].append(record_id)
            self._save_overrides()
        self._audit(user, "DELETE", record_id, {})
        return True

    # ------------------------------------------------------------------- KPIs
    def kpis(self) -> dict:
        defects = self.all()
        total = len(defects)

        def is_status(d: ConsolidatedDefect, status: str) -> bool:
            return (d.consolidated_status or "").lower() == status

        kpis = {
            # Cross-system totals (from reconciliation meta)
            "total_in_smartsheet": self._meta.get("total_in_smartsheet", 0),
            "total_in_github": self._meta.get("total_in_github", 0),
            "issue_statuses_count": self._meta.get("issue_statuses_count", total),
            "matched_defects": self._meta.get("matched_defects", 0),
            "missing_in_github": self._meta.get("missing_in_github", 0),
            "linked_to_github": self._meta.get("linked_to_github", 0),
            "not_linked_to_github": self._meta.get("not_linked_to_github", 0),
            # Status counts (from the Issue Statuses consolidated set)
            "total_defects": total,
            "open_defects": sum(1 for d in defects if is_status(d, "open")),
            "in_progress": sum(1 for d in defects if is_status(d, "in progress")),
            "closed_defects": sum(1 for d in defects if is_status(d, "closed")),
            "unassigned_defects": sum(1 for d in defects if not d.assigned_developer),
            "duplicates": sum(1 for d in defects if d.data_validation_status == "Duplicate"),
            "requires_review": sum(
                1 for d in defects if d.data_validation_status == "Requires Review"
            ),
            "last_refreshed": self.last_refreshed,
            "reconciled_at": self.reconciled_at,
        }
        return kpis

    # ------------------------------------------------------------- persistence
    def _load_overrides(self) -> None:
        path = self.settings.overrides_path
        if path.exists():
            try:
                self._overrides = json.loads(path.read_text(encoding="utf-8"))
                self._overrides.setdefault("updates", {})
                self._overrides.setdefault("deleted", [])
                self._overrides.setdefault("created", [])
            except (json.JSONDecodeError, OSError):
                pass

    def _save_overrides(self) -> None:
        self.settings.overrides_path.write_text(
            json.dumps(self._overrides, indent=2, default=str), encoding="utf-8"
        )

    # ------------------------------------------------------------------- logs
    def _audit(self, user: str, action: str, record_id: str, details: dict) -> None:
        line = json.dumps(
            {
                "ts": datetime.now().isoformat(timespec="seconds"),
                "user": user,
                "action": action,
                "record_id": record_id,
                "details": details,
            },
            default=str,
        )
        with open(self.settings.audit_log_path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def _log_execution(self, message: str) -> None:
        with open(self.settings.execution_log_path, "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now().isoformat(timespec='seconds')} {message}\n")

    def read_audit(self, limit: int = 200) -> list[dict]:
        path = self.settings.audit_log_path
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
        out = []
        for ln in lines:
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
        return list(reversed(out))
