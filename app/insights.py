"""Insights / analytics engine for the interactive "Insights" page.

Recomputes the equivalent of the workbook's PivotTable sheets (GitHub Issue
Summary, Celanese Defects by priority, Created/Closed this week, Issues Deployed
for UAT, by module / issue source / promotion status) directly from the
consolidated dataset, so the page is always fresh and never depends on the
fragile cached Excel pivots (which openpyxl drops on save).

Everything is filterable by Issue Source, Module, Priority and Status.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Optional

from .models import ConsolidatedDefect
from .store import DefectStore

_DT_FORMATS = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
    "%m/%d/%Y %I:%M:%S %p",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y",
)

_SPLIT_OWNERS = re.compile(r"[;/,]")


def _parse_date(value) -> Optional[date]:
    if value is None:
        return None
    s = str(value).strip().replace("Z", "")
    if not s:
        return None
    if "T" in s:
        s = s.split(".")[0]
    for fmt in _DT_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        return None


def norm_priority(p: Optional[str]) -> str:
    """Collapse raw priority strings into the standard buckets used on the UI."""
    if not p:
        return "Unspecified"
    pl = p.lower()
    if "critical" in pl or "urgent" in pl or "go live" in pl or "go-live" in pl:
        return "Critical/Urgent"
    if "high" in pl:
        return "High"
    if "medium" in pl or "moderate" in pl:
        return "Medium"
    if "low" in pl or "minor" in pl:
        return "Low"
    return p


# Consolidated status mirrors GitHub's OPEN/CLOSED flag, so the matrix uses
# those two columns (there is no separate "In Progress" bucket anymore).
_STATUS_COLS = ["Open", "Closed"]


def _is_uat(d: ConsolidatedDefect) -> bool:
    dp = (d.development_progress or "").lower()
    return "uat" in dp and "deployed" in dp


def _owners(raw: Optional[str]) -> list[str]:
    return [o.strip() for o in _SPLIT_OWNERS.split(raw or "") if o.strip()]


# --------------------------------------------------------------------- filters
def _distinct(defects, attr: str, fallback: str) -> list[str]:
    seen: list[str] = []
    s: set[str] = set()
    for d in defects:
        v = (getattr(d, attr, None) or "").strip() or fallback
        if v not in s:
            s.add(v)
            seen.append(v)
    return sorted(seen, key=lambda x: (x == fallback, x.lower()))


def _match(value: Optional[str], wanted: list[str], fallback: str) -> bool:
    if not wanted:
        return True
    v = (value or "").strip() or fallback
    return v.lower() in {w.lower() for w in wanted}


def _apply_filters(defects, f: dict) -> list:
    src = f.get("issue_source") or []
    mod = f.get("module") or []
    pri = f.get("priority") or []
    sts = f.get("status") or []
    promo = f.get("promotion") or []
    owner = f.get("owner") or []
    unassigned = f.get("unassigned")
    created_since = _parse_date(f.get("created_since")) if f.get("created_since") else None
    created_before = _parse_date(f.get("created_before")) if f.get("created_before") else None
    closed_since = _parse_date(f.get("closed_since")) if f.get("closed_since") else None
    closed_before = _parse_date(f.get("closed_before")) if f.get("closed_before") else None
    open_as_of = _parse_date(f.get("open_as_of")) if f.get("open_as_of") else None
    out = []
    for d in defects:
        if not _match(d.issue_source, src, "(none)"):
            continue
        if not _match(d.module, mod, "(none)"):
            continue
        if pri and norm_priority(d.priority) not in set(pri):
            continue
        if not _match(d.consolidated_status, sts, "Unknown"):
            continue
        if not _match(d.development_progress, promo, "(none)"):
            continue
        if owner:
            devs = (d.assigned_developer or "").lower()
            if not any(o.lower() in devs for o in owner):
                continue
        if unassigned and d.assigned_developer:
            continue
        if created_since:
            cd = _parse_date(d.github_created or d.created_date)
            if not cd or cd < created_since:
                continue
        if created_before:
            cd = _parse_date(d.github_created or d.created_date)
            if not cd or cd > created_before:
                continue
        if closed_since:
            if (d.consolidated_status or "").lower() != "closed":
                continue
            ud = _parse_date(d.github_last_updated or d.last_updated)
            if not ud or ud < closed_since:
                continue
        if closed_before:
            if (d.consolidated_status or "").lower() != "closed":
                continue
            ud = _parse_date(d.github_last_updated or d.last_updated)
            if not ud or ud > closed_before:
                continue
        if open_as_of:
            # mirror the summary grid: a defect is "open as of" a day when it
            # existed by then and had not been closed on/before that day.
            cd = _parse_date(d.github_created or d.created_date)
            if not cd or cd > open_as_of:
                continue
            if (d.consolidated_status or "").lower() == "closed":
                ud = _parse_date(d.github_last_updated or d.last_updated)
                if ud is None or ud <= open_as_of:
                    continue
        out.append(d)
    return out


# Compact projection used by the drill-down modal.
_DRILL_FIELDS = [
    "record_id", "github_issue_id", "customer_defect_id", "defect_title",
    "consolidated_status", "assigned_developer", "ntt_category", "priority", "module",
    "issue_source", "development_progress", "last_updated", "github_url",
]


def drill_defects(store: DefectStore, filters: dict) -> list[dict]:
    """Return the actual defect rows behind a clicked Insights number, using the
    SAME filtering/normalization as the page so the list matches the count."""
    rows = _apply_filters(store.all(), filters)
    rows.sort(key=lambda d: (d.github_issue_id is None, str(d.github_issue_id or "")))
    return [{k: getattr(d, k, None) for k in _DRILL_FIELDS} for d in rows]


# --------------------------------------------------------------------- builder
def build_insights(store: DefectStore, filters: Optional[dict] = None) -> dict:
    filters = filters or {}
    all_defects = store.all()

    # Available filter options (always from the full set so users can widen).
    options = {
        "issue_source": _distinct(all_defects, "issue_source", "(none)"),
        "module": _distinct(all_defects, "module", "(none)"),
        "priority": ["Critical/Urgent", "High", "Medium", "Low", "Unspecified"],
        "status": ["Open", "In Progress", "Closed", "Unknown"],
    }

    defects = _apply_filters(all_defects, filters)

    def is_status(d, s):
        return (d.consolidated_status or "").lower() == s.lower()

    today = date.today()
    monday = today - timedelta(days=today.weekday())

    # ---- KPI tiles ----
    created_week = [d for d in defects if (_parse_date(d.github_created or d.created_date) or date.min) >= monday]
    closed_week = [
        d for d in defects
        if is_status(d, "Closed")
        and (_parse_date(d.github_last_updated or d.last_updated) or date.min) >= monday
    ]
    kpis = {
        "total": len(defects),
        "open": sum(1 for d in defects if is_status(d, "Open")),
        "in_progress": sum(1 for d in defects if is_status(d, "In Progress")),
        "closed": sum(1 for d in defects if is_status(d, "Closed")),
        "urgent": sum(1 for d in defects if norm_priority(d.priority) == "Critical/Urgent"),
        "unassigned": sum(1 for d in defects if not d.assigned_developer),
        "created_this_week": len(created_week),
        "closed_this_week": len(closed_week),
        "deployed_uat": sum(1 for d in defects if _is_uat(d)),
    }

    # ---- Module x Status matrix (the color-coded centrepiece) ----
    mod_counter: dict[str, Counter] = {}
    for d in defects:
        mod = (d.module or "(none)").strip() or "(none)"
        st = d.consolidated_status if d.consolidated_status in _STATUS_COLS else None
        c = mod_counter.setdefault(mod, Counter())
        c["_total"] += 1
        if st:
            c[st] += 1
    matrix_rows = []
    for mod, c in mod_counter.items():
        matrix_rows.append({
            "label": mod,
            "cells": [c.get(s, 0) for s in _STATUS_COLS],
            "total": c["_total"],
        })
    matrix_rows.sort(key=lambda r: r["total"], reverse=True)
    col_totals = [sum(r["cells"][i] for r in matrix_rows) for i in range(len(_STATUS_COLS))]
    matrix = {
        "columns": _STATUS_COLS,
        "rows": matrix_rows,
        "col_totals": col_totals,
        "grand_total": sum(col_totals),
        "max_cell": max([max(r["cells"]) for r in matrix_rows], default=0),
    }

    # ---- Priority breakdown (open vs closed split, like the Celanese pivot) ----
    pri_counter: dict[str, Counter] = {}
    for d in defects:
        p = norm_priority(d.priority)
        c = pri_counter.setdefault(p, Counter())
        c["_total"] += 1
        if is_status(d, "Open") or is_status(d, "In Progress"):
            c["open"] += 1
        elif is_status(d, "Closed"):
            c["closed"] += 1
    pri_order = ["Critical/Urgent", "High", "Medium", "Low", "Unspecified"]
    priority = [
        {"label": p, "open": pri_counter[p].get("open", 0),
         "closed": pri_counter[p].get("closed", 0), "total": pri_counter[p]["_total"]}
        for p in pri_order if p in pri_counter
    ]

    # ---- Promotion / workflow status (GitHub project board phase) ----
    promo = Counter((d.development_progress or "(none)").strip() or "(none)" for d in defects)

    # ---- Issue source ----
    isrc = Counter((d.issue_source or "(none)").strip() or "(none)" for d in defects)

    # ---- Weekly trend (Mon..today): created vs closed per day ----
    days = [(monday + timedelta(days=i)) for i in range((today - monday).days + 1)]
    created_by_day = Counter()
    closed_by_day = Counter()
    for d in defects:
        cd = _parse_date(d.github_created or d.created_date)
        if cd and cd >= monday:
            created_by_day[cd.isoformat()] += 1
        if is_status(d, "Closed"):
            ud = _parse_date(d.github_last_updated or d.last_updated)
            if ud and ud >= monday:
                closed_by_day[ud.isoformat()] += 1
    weekly = {
        "days": [dd.isoformat() for dd in days],
        "created": [created_by_day.get(dd.isoformat(), 0) for dd in days],
        "closed": [closed_by_day.get(dd.isoformat(), 0) for dd in days],
    }

    # ---- Issues deployed for UAT (list) ----
    uat = [
        {
            "github_issue_id": d.github_issue_id,
            "defect_title": d.defect_title,
            "module": d.module,
            "assigned_developer": d.assigned_developer,
            "priority": d.priority,
            "promotion_status": d.development_progress,
            "record_id": d.record_id,
        }
        for d in defects if _is_uat(d)
    ]

    # ---- Owner workload (open / in-progress) ----
    owner_c: Counter = Counter()
    for d in defects:
        if (d.consolidated_status or "").lower() not in {"open", "in progress"}:
            continue
        for o in _owners(d.assigned_developer):
            owner_c[o] += 1

    # ---- Summary: last 7 business-day progress (most recent day first) ----
    def _biz_days(n: int) -> list:
        out, cur = [], today
        while len(out) < n:
            if cur.weekday() < 5:  # Mon–Fri only
                out.append(cur)
            cur -= timedelta(days=1)
        return out

    def _ordinal(n: int) -> str:
        suf = "th" if 11 <= (n % 100) <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return f"{n}{suf}"

    yesterday = today - timedelta(days=1)
    prog_days = _biz_days(7)
    day_meta = []
    for d in prog_days:
        if d == today:
            lbl = "Today"
        elif d == yesterday:
            lbl = "Yesterday"
        else:
            lbl = f"{_ordinal(d.day)} {d.strftime('%b')}"
        day_meta.append({"key": d.isoformat(), "label": lbl})

    # Parse each defect's created / closed dates once for the as-of snapshots.
    parsed = []
    for d in defects:
        cd = _parse_date(d.github_created or d.created_date)
        is_closed = (d.consolidated_status or "").lower() == "closed"
        xd = _parse_date(d.github_last_updated or d.last_updated) if is_closed else None
        parsed.append((d, cd, is_closed, xd))

    def _as_of(day):
        s = dict(total=0, open=0, closed=0, created_on=0, closed_on=0, ageing=0, urgent=0)
        cutoff = day - timedelta(days=30)
        for d, cd, is_closed, xd in parsed:
            if not cd or cd > day:
                continue  # not created yet as of this day
            s["total"] += 1
            if cd == day:
                s["created_on"] += 1
            closed_as_of = is_closed and (xd is None or xd <= day)
            if closed_as_of:
                s["closed"] += 1
                if xd == day:
                    s["closed_on"] += 1
            else:
                s["open"] += 1
                if cd <= cutoff:
                    s["ageing"] += 1
                if norm_priority(d.priority) == "Critical/Urgent":
                    s["urgent"] += 1
        return s

    stats = [_as_of(d) for d in prog_days]
    series = lambda k: [s[k] for s in stats]  # noqa: E731
    summary = {
        "days": day_meta,
        "rows": [
            {"metric": "Total defects", "tone": "neutral", "values": series("total"), "drill": "total"},
            {"metric": "Open", "tone": "warn", "values": series("open"), "drill": "open"},
            {"metric": "Closed", "tone": "good", "values": series("closed"), "drill": "closed_cum"},
            {"metric": "Ageing open (30+ days)", "tone": "bad", "values": series("ageing"), "drill": "ageing"},
            {"metric": "Critical / Urgent open", "tone": "bad", "values": series("urgent"), "drill": "urgent"},
            {"metric": "Created (that day)", "tone": "info", "values": series("created_on"), "drill": "created_on"},
            {"metric": "Closed (that day)", "tone": "good", "values": series("closed_on"), "drill": "closed_on"},
        ],
    }

    return {
        "summary": summary,
        "applied": filters,
        "options": options,
        "kpis": kpis,
        "matrix": matrix,
        "priority": priority,
        "promotion": promo.most_common(12),
        "issue_source": isrc.most_common(12),
        "weekly": weekly,
        "uat": uat,
        "owners": owner_c.most_common(12),
        "last_refreshed": store.last_refreshed,
        "reconciled_at": store.reconciled_at,
    }
