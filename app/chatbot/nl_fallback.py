"""Deterministic natural-language router used when no LLM is configured.

Maps a user message to one grounded analytics tool call. This keeps the whole
chatbot functional offline (BRD: AI responses grounded in retrieved data).
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

ID_RE = re.compile(r"#?\b(\d{2,6})\b")

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7,
    "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _month_end(year: int, month: int) -> date:
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


def _date_route(m: str) -> dict[str, Any] | None:
    """Best-effort offline parser for time-based defect questions."""
    if not any(k in m for k in (
        "week", "month", "today", "yesterday", "monday", "since", "after",
        "before", "created on", "closed on", "date by date", "day by day",
        "2024", "2025", "2026", "2027",
    )) and not re.search(r"\b(19|20)\d{2}\b", m):
        return None

    today = date.today()
    kwargs: dict[str, Any] = {}
    if "closed" in m or "resolved" in m:
        kwargs["status"] = "Closed"
    elif "open" in m:
        kwargs["status"] = "Open"
    elif "in progress" in m or "in-progress" in m:
        kwargs["status"] = "In Progress"
    if "smartsheet" in m or "smart sheet" in m:
        kwargs["source"] = "smartsheet"
    elif "github" in m or "git issue" in m:
        kwargs["source"] = "github"
    kwargs["date_field"] = "created" if "created" in m else "updated"
    if "date by date" in m or "day by day" in m:
        kwargs["granularity"] = "daily"

    # Explicit "<day> <month> <year>" e.g. 1st nov 2026
    md = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]{3,9})\s+((?:19|20)\d{2})", m)
    mon_year = re.search(r"\b([a-z]{3,9})\s+((?:19|20)\d{2})\b", m)
    if md:
        day = int(md.group(1)); mon = _MONTHS.get(md.group(2)[:3]); yr = int(md.group(3))
        if mon:
            d = date(yr, mon, day)
            kwargs["start_date"] = d.isoformat()
            if "before" in m:
                kwargs["end_date"] = d.isoformat(); kwargs.pop("start_date", None)
    elif mon_year:
        mon = _MONTHS.get(mon_year.group(1)[:3]); yr = int(mon_year.group(2))
        if mon:
            kwargs["start_date"] = date(yr, mon, 1).isoformat()
            kwargs["end_date"] = _month_end(yr, mon).isoformat()
    elif "this week" in m or ("week" in m and "last" not in m):
        monday = today - timedelta(days=today.weekday())
        kwargs["start_date"] = monday.isoformat(); kwargs["end_date"] = today.isoformat()
    elif "last week" in m or "past week" in m:
        monday = today - timedelta(days=today.weekday() + 7)
        kwargs["start_date"] = monday.isoformat()
        kwargs["end_date"] = (monday + timedelta(days=6)).isoformat()
    elif "past monday" in m or "last monday" in m:
        monday = today - timedelta(days=today.weekday())
        if "past" in m or monday == today:
            monday = today - timedelta(days=today.weekday())
        kwargs["start_date"] = monday.isoformat()
    elif "this month" in m:
        kwargs["start_date"] = today.replace(day=1).isoformat()
        kwargs["end_date"] = today.isoformat()
    elif "today" in m:
        kwargs["start_date"] = today.isoformat(); kwargs["end_date"] = today.isoformat()

    # Only route if we derived a usable date constraint.
    if kwargs.get("start_date") or kwargs.get("end_date"):
        return kwargs
    return None


def _status_in(text: str) -> str | None:
    if "in progress" in text or "in-progress" in text or "under development" in text:
        return "In Progress"
    if "closed" in text or "resolved" in text or "completed" in text:
        return "Closed"
    if "open" in text:
        return "Open"
    return None


# Priority keywords -> the value passed to count/list tools. The tool itself
# maps synonyms (critical/blocker/P1 -> Urgent) so pass the spoken word through.
_PRIORITY_WORDS = (
    "critical", "blocker", "urgent", "highest", "p1", "sev1",
    "high", "p2", "medium", "moderate", "p3", "low", "minor", "p4",
)


def _priority_in(text: str) -> str | None:
    for kw in _PRIORITY_WORDS:
        if re.search(rf"\b{re.escape(kw)}\b", text):
            return kw
    return None


def route(message: str) -> tuple[str, dict[str, Any]]:
    """Return (tool_name, kwargs) for a message."""
    m = (message or "").lower().strip()

    # Time/date-based questions (this week, since a date, in a month, day by day)
    date_kwargs = _date_route(m)
    if date_kwargs is not None:
        return "defects_by_date", date_kwargs

    # Reconciliation gaps
    if ("smartsheet" in m and "github" in m) or "reconcil" in m:
        if "duplicate" in m:
            return "reconciliation_gaps", {"kind": "duplicates"}
        if "mismatch" in m or "different status" in m or "inconsistent" in m:
            return "reconciliation_gaps", {"kind": "mismatched_status"}
        # "smartsheet but missing in github"
        if re.search(r"smart\s*sheet.*(missing|not).*git", m) or re.search(r"missing in git", m):
            return "reconciliation_gaps", {"kind": "smartsheet_only"}
        if re.search(r"git.*(missing|not).*smart", m) or re.search(r"not (available |)in smart", m):
            return "reconciliation_gaps", {"kind": "github_only"}
    if "duplicate" in m:
        return "reconciliation_gaps", {"kind": "duplicates"}
    if "mismatch" in m or "inconsistent status" in m:
        return "reconciliation_gaps", {"kind": "mismatched_status"}

    # Aging / oldest / stale questions
    if any(w in m for w in ("oldest", "stale", "aging", "ageing", "how old", "longest open", "long-open", "overdue")):
        return "aging_report", {"status": _status_in(m) or "Open"}

    # "Top / most / highest / which <dimension>" ranking questions
    if any(w in m for w in ("most", "highest", "top ", "largest", "maximum", " max ", "greatest", "biggest", "which", "rank")):
        dim = None
        if "module" in m:
            dim = "module"
        elif "owner" in m or "developer" in m or "assignee" in m or "who " in m:
            dim = "owner"
        elif "priority" in m:
            dim = "priority"
        elif "issue source" in m or "source" in m:
            dim = "issue_source"
        elif "phase" in m or "workflow" in m or "promotion" in m:
            dim = "promotion"
        elif "category" in m:
            dim = "category"
        if dim:
            kwargs: dict[str, Any] = {"group_by": dim}
            st = _status_in(m)
            pr = _priority_in(m)
            if st:
                kwargs["status"] = st
            if pr:
                kwargs["priority"] = pr
            return "top_groups", kwargs

    # Distribution by a field
    if "issue source" in m or "issuesource" in m or "by source" in m:
        return "defect_distribution", {"group_by": "issue_source"}
    if "by module" in m or "per module" in m or "module" in m and "distribution" in m:
        return "defect_distribution", {"group_by": "module"}
    if "by priority" in m or "per priority" in m or ("priority" in m and "distribution" in m):
        return "defect_distribution", {"group_by": "priority"}
    if "by category" in m or "ntt category" in m:
        return "defect_distribution", {"group_by": "ntt_category"}

    # Unassigned
    if "unassigned" in m or "not assigned" in m or ("without" in m and "developer" in m):
        return "unassigned_defects", {}

    # Developer distribution
    if ("developer" in m or "assignee" in m or "owner" in m) and (
        "each" in m or "per " in m or "distribution" in m or "how many" in m
        or "highest" in m or "most" in m or "who" in m
    ):
        return "developer_distribution", {"open_only": "open" in m or "progress" in m}

    # Defects assigned to a specific developer
    mt = re.search(r"assigned to ([a-z0-9@._\- ]{3,})", m)
    if mt and "each" not in m:
        name = mt.group(1).strip().split("?")[0].strip()
        return "list_defects", {"developer": name}

    # Detail / progress of a specific defect
    if any(k in m for k in ("detail", "progress of", "status of", "about defect", "show defect")):
        gid = ID_RE.search(m)
        if gid:
            return "defect_detail", {"identifier": gid.group(1)}

    # Summary / report
    if any(k in m for k in ("summary", "overview", "overall", "dashboard", "report", "distribution")):
        if "developer" in m:
            return "developer_distribution", {}
        return "summary", {}

    # Counts
    status = _status_in(m)
    priority = _priority_in(m)
    if any(k in m for k in ("how many", "count", "number of", "total")):
        kwargs: dict[str, Any] = {}
        if status:
            kwargs["status"] = status
        if priority:
            kwargs["priority"] = priority
        if kwargs:
            return "count_defects", kwargs
        return "summary", {}

    # List with status/priority
    if (status or priority) and any(k in m for k in ("list", "show", "provide", "which", "all")):
        kwargs = {}
        if status:
            kwargs["status"] = status
        if priority:
            kwargs["priority"] = priority
        return "list_defects", kwargs
    if status or priority:
        kwargs = {}
        if status:
            kwargs["status"] = status
        if priority:
            kwargs["priority"] = priority
        return "count_defects", kwargs

    # A bare id
    gid = ID_RE.search(m)
    if gid and len(m) < 20:
        return "defect_detail", {"identifier": gid.group(1)}

    # Fallback: free-text search
    return "search_defects", {"text": message.strip()}
