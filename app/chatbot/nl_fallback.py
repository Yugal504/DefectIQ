"""Deterministic natural-language router used when no LLM is configured.

Maps a user message to one grounded analytics tool call. This keeps the whole
chatbot functional offline (BRD: AI responses grounded in retrieved data).
"""
from __future__ import annotations

import re
from typing import Any

ID_RE = re.compile(r"#?\b(\d{2,6})\b")


def _status_in(text: str) -> str | None:
    if "in progress" in text or "in-progress" in text or "under development" in text:
        return "In Progress"
    if "closed" in text or "resolved" in text or "completed" in text:
        return "Closed"
    if "open" in text:
        return "Open"
    return None


def route(message: str) -> tuple[str, dict[str, Any]]:
    """Return (tool_name, kwargs) for a message."""
    m = (message or "").lower().strip()

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
    if any(k in m for k in ("how many", "count", "number of", "total")):
        if status:
            return "count_defects", {"status": status}
        return "summary", {}

    # List with status
    if status and any(k in m for k in ("list", "show", "provide", "which", "all")):
        return "list_defects", {"status": status}
    if status:
        return "count_defects", {"status": status}

    # A bare id
    gid = ID_RE.search(m)
    if gid and len(m) < 20:
        return "defect_detail", {"identifier": gid.group(1)}

    # Fallback: free-text search
    return "search_defects", {"text": message.strip()}
