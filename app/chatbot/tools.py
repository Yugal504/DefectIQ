"""Grounded analytics tools the agent can call.

Every tool operates ONLY on the consolidated dataset in the store, so the
chatbot never invents defect information (BRD 5.3.3 / risk: LLM hallucination).
Each tool returns a structured dict: {summary, count, rows, extra}.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Optional

from ..models import ConsolidatedDefect
from ..reconciliation import _classify
from ..store import DefectStore

# Accepted date/datetime formats across GitHub (ISO Z) and Smartsheet.
_DT_FORMATS = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
    "%m/%d/%Y %I:%M:%S %p",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y",
)


def _parse_dt(value) -> Optional[datetime]:
    """Parse a GitHub/Smartsheet date string into a datetime (date-level ok)."""
    if value is None:
        return None
    s = str(value).strip().replace("Z", "")
    if not s:
        return None
    if "T" in s:
        s = s.split(".")[0]
    for fmt in _DT_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None

# Compact row projection for responses / tables.
ROW_FIELDS = [
    "record_id",
    "customer_defect_id",
    "github_issue_id",
    "defect_title",
    "consolidated_status",
    "assigned_developer",
    "priority",
    "source_availability",
    "last_updated",
    "github_url",
]


def _row(d: ConsolidatedDefect) -> dict:
    return {f: getattr(d, f) for f in ROW_FIELDS}


def _match_status(d: ConsolidatedDefect, status: Optional[str]) -> bool:
    if not status:
        return True
    return (d.consolidated_status or "").lower() == status.strip().lower()


def _match_dev(d: ConsolidatedDefect, dev: Optional[str]) -> bool:
    if not dev:
        return True
    return dev.strip().lower() in (d.assigned_developer or "").lower()


def _match_source(d: ConsolidatedDefect, source: Optional[str]) -> bool:
    if not source:
        return True
    return (d.source_availability or "").lower() == source.strip().lower()


def _match_priority(d: ConsolidatedDefect, priority: Optional[str]) -> bool:
    if not priority:
        return True
    return priority.strip().lower() in (d.priority or "").lower()


class DefectTools:
    def __init__(self, store: DefectStore) -> None:
        self.store = store

    # ----------------------------------------------------------------- tools
    def summary(self) -> dict:
        k = self.store.kpis()
        summary = (
            f"{k['issue_statuses_count']} defects in the Issue Statuses tracker: "
            f"{k['open_defects']} open, {k['in_progress']} in progress, "
            f"{k['closed_defects']} closed; {k['unassigned_defects']} unassigned. "
            f"Smartsheet total {k['total_in_smartsheet']}, GitHub total {k['total_in_github']}, "
            f"matched {k['matched_defects']}, missing in GitHub {k['missing_in_github']}."
        )
        return {"summary": summary, "count": k["issue_statuses_count"], "rows": [], "extra": k}

    def count_defects(
        self,
        status: Optional[str] = None,
        source: Optional[str] = None,
        developer: Optional[str] = None,
        priority: Optional[str] = None,
    ) -> dict:
        rows = [
            d
            for d in self.store.all()
            if _match_status(d, status)
            and _match_source(d, source)
            and _match_dev(d, developer)
            and _match_priority(d, priority)
        ]
        parts = []
        if status:
            parts.append(f"status '{status}'")
        if source:
            parts.append(f"source '{source}'")
        if developer:
            parts.append(f"developer '{developer}'")
        if priority:
            parts.append(f"priority '{priority}'")
        desc = (" with " + ", ".join(parts)) if parts else ""
        return {
            "summary": f"{len(rows)} defect(s){desc}.",
            "count": len(rows),
            "rows": [_row(d) for d in rows[:50]],
            "extra": {},
        }

    def list_defects(
        self,
        status: Optional[str] = None,
        source: Optional[str] = None,
        developer: Optional[str] = None,
        priority: Optional[str] = None,
        limit: int = 25,
    ) -> dict:
        rows = [
            d
            for d in self.store.all()
            if _match_status(d, status)
            and _match_source(d, source)
            and _match_dev(d, developer)
            and _match_priority(d, priority)
        ]
        return {
            "summary": f"Showing {min(limit, len(rows))} of {len(rows)} matching defect(s).",
            "count": len(rows),
            "rows": [_row(d) for d in rows[:limit]],
            "extra": {},
        }

    def defect_detail(self, identifier: str) -> dict:
        ident = (identifier or "").strip().lstrip("#").lower()
        for d in self.store.all():
            if ident in {
                (d.github_issue_id or "").lower(),
                (d.customer_defect_id or "").lower(),
                (d.record_id or "").lower(),
            }:
                return {
                    "summary": f"Defect {d.defect_title or d.record_id}.",
                    "count": 1,
                    "rows": [d.model_dump()],
                    "extra": {},
                }
        return {"summary": f"No defect found matching '{identifier}'.", "count": 0, "rows": [], "extra": {}}

    def developer_distribution(self, open_only: bool = False) -> dict:
        counter: Counter = Counter()
        for d in self.store.all():
            if open_only and (d.consolidated_status or "").lower() not in {"open", "in progress"}:
                continue
            dev = d.assigned_developer or "(unassigned)"
            counter[dev] += 1
        ranked = counter.most_common()
        rows = [{"developer": k, "count": v} for k, v in ranked]
        top = ", ".join(f"{k} ({v})" for k, v in ranked[:5])
        scope = "open/in-progress " if open_only else ""
        return {
            "summary": f"{len(ranked)} developers have {scope}defects. Top: {top}.",
            "count": len(ranked),
            "rows": rows,
            "extra": {},
        }

    def defect_distribution(self, group_by: str = "issue_source") -> dict:
        field_map = {
            "issue_source": "issue_source",
            "source": "source_availability",
            "module": "module",
            "priority": "priority",
            "status": "consolidated_status",
            "ntt_category": "ntt_category",
        }
        gb = (group_by or "issue_source").strip().lower()
        field = field_map.get(gb, "issue_source")
        counter: Counter = Counter()
        for d in self.store.all():
            counter[getattr(d, field) or "(none)"] += 1
        ranked = counter.most_common()
        rows = [{"label": k, "count": v} for k, v in ranked]
        top = ", ".join(f"{k} ({v})" for k, v in ranked[:5])
        return {
            "summary": f"Defects by {gb}: {top}." if ranked else f"No data for {gb}.",
            "count": len(ranked),
            "rows": rows,
            "extra": {},
        }

    def unassigned_defects(self) -> dict:
        rows = [d for d in self.store.all() if not d.assigned_developer]
        return {
            "summary": f"{len(rows)} unassigned defect(s).",
            "count": len(rows),
            "rows": [_row(d) for d in rows[:50]],
            "extra": {},
        }

    def reconciliation_gaps(self, kind: str = "smartsheet_only") -> dict:
        kind = (kind or "").strip().lower()
        defects = self.store.all()
        if kind in {"smartsheet_only", "smartsheet", "missing_in_github"}:
            rows = [d for d in defects if d.source_availability == "Smartsheet"]
            label = "in Smartsheet but missing in GitHub"
        elif kind in {"github_only", "github", "missing_in_smartsheet"}:
            rows = [d for d in defects if d.source_availability == "GitHub"]
            label = "in GitHub but missing in Smartsheet"
        elif kind in {"duplicate", "duplicates"}:
            rows = [d for d in defects if d.data_validation_status == "Duplicate"]
            label = "flagged as duplicates"
        elif kind in {"mismatch", "mismatched", "mismatched_status"}:
            rows = [
                d
                for d in defects
                if d.source_availability == "Both"
                and d.github_status
                and d.customer_status
                and (d.github_status or "").lower() not in (d.customer_status or "").lower()
                and (d.customer_status or "").lower() not in (d.github_status or "").lower()
            ]
            label = "with mismatched status across systems"
        elif kind in {"requires_review", "review"}:
            rows = [d for d in defects if d.data_validation_status == "Requires Review"]
            label = "that require review"
        else:
            rows = []
            label = f"(unknown gap type '{kind}')"
        return {
            "summary": f"{len(rows)} defect(s) {label}.",
            "count": len(rows),
            "rows": [_row(d) for d in rows[:50]],
            "extra": {},
        }

    def search_defects(self, text: str, limit: int = 25) -> dict:
        q = (text or "").strip().lower()
        rows = []
        if q:
            for d in self.store.all():
                hay = " ".join(
                    str(x or "")
                    for x in (
                        d.defect_title,
                        d.description,
                        d.github_issue_id,
                        d.customer_defect_id,
                        d.assigned_developer,
                        d.module,
                        d.latest_comment,
                    )
                ).lower()
                if q in hay:
                    rows.append(d)
        return {
            "summary": f"{len(rows)} defect(s) matched '{text}'.",
            "count": len(rows),
            "rows": [_row(d) for d in rows[:limit]],
            "extra": {},
        }

    def defects_by_date(
        self,
        status: Optional[str] = None,
        source: Optional[str] = None,
        date_field: str = "updated",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        granularity: str = "total",
    ) -> dict:
        """Count defects filtered by a date range on a created/updated date.

        source: 'smartsheet' queries ALL Smart Sheet Export rows; 'github'/None
        queries the consolidated (GitHub-driven) defects. date_field is
        'created' or 'updated' (updated = GitHub Last Updated / Smartsheet
        Modified). start_date/end_date are 'YYYY-MM-DD' inclusive. granularity
        'daily' returns a date-by-date breakdown.
        """
        src = (source or "").strip().lower()
        field = (date_field or "updated").strip().lower()
        start = _parse_dt(start_date)
        end = _parse_dt(end_date)
        want_status = (status or "").strip().lower() or None

        # Build (label, status_text, date) tuples depending on the source.
        records: list[tuple[str, Optional[str], Optional[datetime]]] = []
        if src in {"smartsheet", "smart sheet", "ss"}:
            scope = "Smartsheet"
            for r in self.store.raw_smartsheet_rows():
                dt = _parse_dt(r.get("created") if field == "created" else r.get("modified"))
                records.append((r.get("action_id") or "", r.get("status"), dt))
        else:
            scope = "GitHub" if src == "github" else "consolidated"
            for d in self.store.all():
                if field == "created":
                    dt = _parse_dt(d.github_created or d.created_date)
                else:
                    dt = _parse_dt(d.github_last_updated or d.last_updated)
                records.append((d.github_issue_id or d.record_id, d.consolidated_status, dt))

        def status_ok(text: Optional[str]) -> bool:
            if not want_status:
                return True
            return _classify(text) == _classify(want_status)

        def date_ok(dt: Optional[datetime]) -> bool:
            if dt is None:
                return False
            if start and dt.date() < start.date():
                return False
            if end and dt.date() > end.date():
                return False
            return True

        matched = [(label, dt) for (label, st, dt) in records if status_ok(st) and date_ok(dt)]
        total = len(matched)

        label_bits = []
        if want_status:
            label_bits.append(f"'{status}'")
        label_bits.append(scope if scope != "consolidated" else "")
        rng = ""
        if start and end:
            rng = f" between {start.date()} and {end.date()}"
        elif start:
            rng = f" on/after {start.date()}"
        elif end:
            rng = f" on/before {end.date()}"
        desc = " ".join(b for b in label_bits if b).strip()
        on = "created" if field == "created" else "last updated/modified"

        if (granularity or "total").strip().lower() == "daily":
            by_day: Counter = Counter()
            for _, dt in matched:
                by_day[dt.date().isoformat()] += 1
            rows = [{"label": day, "count": by_day[day]} for day in sorted(by_day)]
            top = "; ".join(f"{d}: {c}" for d, c in list(sorted(by_day.items()))[-7:])
            return {
                "summary": f"{total} {desc} defect(s){rng} (by {on}), day by day: {top}."
                if total else f"No {desc} defects found{rng} (by {on}).",
                "count": total,
                "rows": rows,
                "extra": {},
            }
        return {
            "summary": f"{total} {desc} defect(s){rng} (by {on})."
            if total else f"No {desc} defects found{rng} (by {on}).",
            "count": total,
            "rows": [],
            "extra": {},
        }


# ------------------------------------------------------------- tool schemas
# JSON schemas for Azure OpenAI function-calling.
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "summary",
            "description": "Overall consolidated defect summary and KPIs (totals, open/closed, reconciliation split).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "count_defects",
            "description": "Count defects, optionally filtered by status, source, developer, or priority.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "Open, In Progress, or Closed"},
                    "source": {"type": "string", "description": "Both, Smartsheet, or GitHub"},
                    "developer": {"type": "string"},
                    "priority": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_defects",
            "description": "List defects with their details, optionally filtered by status/source/developer/priority.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string"},
                    "source": {"type": "string"},
                    "developer": {"type": "string"},
                    "priority": {"type": "string"},
                    "limit": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "defect_detail",
            "description": "Get full details for one defect by GitHub issue id, customer defect id, or record id.",
            "parameters": {
                "type": "object",
                "properties": {"identifier": {"type": "string"}},
                "required": ["identifier"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "developer_distribution",
            "description": "How many defects are assigned to each developer. Set open_only=true for open/in-progress only.",
            "parameters": {
                "type": "object",
                "properties": {"open_only": {"type": "boolean"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "defect_distribution",
            "description": "Break defects down (counts) by a field: issue_source, module, priority, status, source, or ntt_category.",
            "parameters": {
                "type": "object",
                "properties": {
                    "group_by": {
                        "type": "string",
                        "enum": ["issue_source", "module", "priority", "status", "source", "ntt_category"],
                    }
                },
                "required": ["group_by"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "unassigned_defects",
            "description": "List defects that have no assigned developer.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reconciliation_gaps",
            "description": "Reconciliation analysis between Smartsheet and GitHub.",
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": [
                            "smartsheet_only",
                            "github_only",
                            "duplicates",
                            "mismatched_status",
                            "requires_review",
                        ],
                    }
                },
                "required": ["kind"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_defects",
            "description": "Free-text search across defect titles, descriptions, ids, developers, modules and comments.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}, "limit": {"type": "integer"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "defects_by_date",
            "description": (
                "Count defects within a date range, optionally day-by-day. Use for any "
                "time-based question (this week, since a date, in a month, created/closed on dates). "
                "Compute concrete calendar dates yourself from today's date and pass them as "
                "YYYY-MM-DD. 'source'='smartsheet' uses all Smartsheet entries; 'github' (or omit) "
                "uses GitHub/consolidated defects. 'date_field'='updated' means GitHub Last Updated "
                "or Smartsheet Modified (use this as the closed date); 'created' means creation date. "
                "Set granularity='daily' for a date-by-date breakdown."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "Open, In Progress, or Closed"},
                    "source": {"type": "string", "enum": ["smartsheet", "github"]},
                    "date_field": {"type": "string", "enum": ["created", "updated"]},
                    "start_date": {"type": "string", "description": "Inclusive start, YYYY-MM-DD"},
                    "end_date": {"type": "string", "description": "Inclusive end, YYYY-MM-DD"},
                    "granularity": {"type": "string", "enum": ["total", "daily"]},
                },
            },
        },
    },
]
