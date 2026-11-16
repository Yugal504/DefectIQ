"""Reconciliation engine: consolidate GitHub + Smartsheet into one dataset.

Replaces the fragile Excel VLOOKUP chain with a robust Python join on the
SmartSheet Action ID, and computes source availability, a normalized
consolidated status, and a data-validation classification
(Matched / Missing / Duplicate / Requires Review) for every defect.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Optional

from .data_loader import WorkbookData
from .models import ConsolidatedDefect

# Matches the smartsheet action id embedded in GitHub titles, e.g.
# "[PROD - 823] ...", "[PROD 853] ...", "[PROD-820]...".
_TITLE_ACTION_RE = re.compile(r"\[\s*PROD\s*-?\s*(\d+)\s*\]", re.IGNORECASE)

_CLOSED_WORDS = ("closed", "done", "resolved", "complete", "cancelled", "wont fix", "won't fix")
_PROGRESS_WORDS = (
    "progress", "testing", "develop", "triage", "reassigned", "uat",
    "review", "qa", "pending", "assigned", "deployed", "fix",
)
_OPEN_WORDS = ("new", "open", "to be", "backlog", "todo", "to do")


_DATE_FORMATS = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
    "%m/%d/%Y %I:%M:%S %p",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y",
)


def date_only(value: Optional[str]) -> Optional[str]:
    """Return just the calendar date (YYYY-MM-DD), dropping any time component."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    import datetime as _dt

    core = s.replace("Z", "").split(".")[0]
    for fmt in _DATE_FORMATS:
        try:
            return _dt.datetime.strptime(core, fmt).date().isoformat()
        except ValueError:
            continue
    try:
        return _dt.datetime.fromisoformat(core).date().isoformat()
    except ValueError:
        return s  # leave untouched if unparseable


def norm_id(value: Optional[str]) -> Optional[str]:
    """Normalize an identifier: strip whitespace and a trailing '.0'."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    return s


def _classify(text: Optional[str]) -> Optional[str]:
    """Map a free-text status into open / in_progress / closed."""
    if not text:
        return None
    t = text.lower()
    if any(w in t for w in _CLOSED_WORDS):
        return "closed"
    if any(w in t for w in _PROGRESS_WORDS):
        return "in_progress"
    if any(w in t for w in _OPEN_WORDS):
        return "open"
    return None


def _consolidated_status(
    github_status: Optional[str],
    project_status: Optional[str],
    smartsheet_status: Optional[str],
) -> str:
    signals = {
        _classify(github_status),
        _classify(project_status),
        _classify(smartsheet_status),
    }
    signals.discard(None)
    if not signals:
        return "Unknown"
    if signals == {"closed"}:
        return "Closed"
    if "in_progress" in signals:
        return "In Progress"
    if "open" in signals:
        return "Open"
    return "Closed"


def _linked_action_id(gh: dict) -> Optional[str]:
    """Determine the smartsheet action id a GitHub issue maps to."""
    aid = norm_id(gh.get("smartsheet_action_id"))
    if aid:
        return aid
    title = gh.get("title") or ""
    m = _TITLE_ACTION_RE.search(title)
    return m.group(1) if m else None


def _github_url(repo: str, issue_id: Optional[str]) -> Optional[str]:
    if not issue_id:
        return None
    return f"https://github.com/{repo}/issues/{issue_id}"


class ConsolidatedDataset:
    """The reconciled dataset plus derived metadata."""

    def __init__(
        self,
        defects: list[ConsolidatedDefect],
        last_refreshed: Optional[str],
        reconciled_at: str,
        source_path: str,
    ) -> None:
        self.defects = defects
        self.last_refreshed = last_refreshed
        self.reconciled_at = reconciled_at
        self.source_path = source_path


def reconcile(data: WorkbookData, github_repo: str) -> list[ConsolidatedDefect]:
    """Build the consolidated defect list from the **Issue Statuses** sheet.

    The Issue Statuses sheet drives the universe: each row is a Git Issue ID with
    an optional manually-mapped Smart Sheet Action ID. We recompute that sheet's
    VLOOKUPs in Python - enriching each Git Issue ID from GitHub Export and each
    Smart Sheet Action ID from Smart Sheet Export. Rows whose Git Issue ID does
    not resolve to a real GitHub issue (blank formula rows) are skipped.
    """
    gh_by_id: dict[str, dict] = {}
    for r in data.github_rows:
        gid = norm_id(r.get("issue_id"))
        if gid and gid not in gh_by_id:
            gh_by_id[gid] = r

    ss_by_action: dict[str, dict] = {}
    for r in data.smartsheet_rows:
        aid = norm_id(r.get("action_id"))
        if aid and aid not in ss_by_action:
            ss_by_action[aid] = r

    seen_git: set[str] = set()
    defects: list[ConsolidatedDefect] = []
    for row in data.issue_status_rows:
        gid = norm_id(row.get("git_issue_id"))
        if not gid:
            continue
        gh = gh_by_id.get(gid)
        if gh is None:
            continue  # blank Issue Statuses row (ID not present in GitHub Export)

        aid = norm_id(row.get("smart_sheet_action_id"))
        ss = ss_by_action.get(aid) if aid else None
        has_ss_id = aid is not None
        source = "Both" if has_ss_id else "GitHub"

        gh_status = gh.get("status")
        proj_status = gh.get("project_status")
        ss_status = ss.get("status") if ss else None
        consolidated = _consolidated_status(gh_status, proj_status, ss_status)
        assigned = gh.get("assigned_to")

        status_mismatch = bool(
            ss
            and gh_status
            and ss_status
            and _consolidated_status(gh_status, proj_status, None)
            != _consolidated_status(None, None, ss_status)
        )
        is_dup = gid in seen_git
        seen_git.add(gid)
        if is_dup:
            validation = "Duplicate"
        elif not has_ss_id:
            validation = "Missing"  # GitHub issue not linked to a Smartsheet action
        elif has_ss_id and ss is None:
            validation = "Requires Review"  # mapped action id not found in Smartsheet
        elif status_mismatch:
            validation = "Requires Review"
        else:
            validation = "Matched"

        defects.append(
            ConsolidatedDefect(
                record_id=f"GH-{gid}",
                customer_defect_id=aid,
                github_issue_id=gid,
                defect_title=gh.get("title") or (ss.get("title") if ss else None),
                description=(ss.get("description") if ss else None),
                customer_status=ss_status,
                github_status=gh_status,
                consolidated_status=consolidated,
                assigned_developer=assigned,
                priority=gh.get("priority") or (ss.get("priority") if ss else None),
                github_priority=gh.get("priority"),
                customer_priority=(ss.get("priority") if ss else None),
                created_date=date_only(gh.get("created") or (ss.get("created") if ss else None)),
                last_updated=date_only(gh.get("last_updated") or (ss.get("modified") if ss else None)),
                github_created=date_only(gh.get("created")),
                github_last_updated=date_only(gh.get("last_updated")),
                customer_created=date_only(ss.get("created") if ss else None),
                customer_modified=date_only(ss.get("modified") if ss else None),
                development_progress=proj_status,
                latest_comment=gh.get("latest_comment") or (ss.get("comments") if ss else None),
                module=gh.get("module") or (ss.get("application") if ss else None),
                ntt_category=(ss.get("ntt_category") if ss else None),
                labels=gh.get("labels"),
                source_availability=source,
                github_url=_github_url(github_repo, gid),
                data_validation_status=validation,
                issue_source=gh.get("issue_source"),
            )
        )

    return defects


def reconciliation_meta(data: WorkbookData, defects: list[ConsolidatedDefect]) -> dict:
    """Cross-system counts derived from the Issue Statuses reconciliation."""
    github_total = len({norm_id(r.get("issue_id")) for r in data.github_rows if norm_id(r.get("issue_id"))})
    ss_action_ids = {norm_id(r.get("action_id")) for r in data.smartsheet_rows if norm_id(r.get("action_id"))}
    smartsheet_total = len(ss_action_ids)

    issue_statuses_count = len(defects)
    linked = sum(1 for d in defects if d.customer_defect_id)  # has a Smart Sheet Action ID
    not_linked = issue_statuses_count - linked
    matched = sum(1 for d in defects if d.data_validation_status == "Matched")

    # Smartsheet actions that are never referenced by any Issue Statuses row.
    linked_action_ids = {d.customer_defect_id for d in defects if d.customer_defect_id}
    missing_in_github = len(ss_action_ids - linked_action_ids)

    return {
        "total_in_smartsheet": smartsheet_total,
        "total_in_github": github_total,
        "issue_statuses_count": issue_statuses_count,
        "matched_defects": matched,
        "missing_in_github": missing_in_github,
        "linked_to_github": linked,
        "not_linked_to_github": not_linked,
    }
