"""Load and normalize the GitHub Export and Smart Sheet Export worksheets.

This is the data-access layer for the Excel-based MVP. It reads the raw
worksheets into lists of plain dicts keyed by meaningful field names, so the
rest of the application never depends on column letters.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import openpyxl


# ----------------------------------------------------------------------
# Column maps (0-based index in each worksheet row).
# Derived from the actual Cockpit_Issue_Tracker.xlsm structure.
# ----------------------------------------------------------------------
GITHUB_COLS = {
    "issue_id": 0,  # A  IssueID
    "title": 1,  # B  Title
    "status": 2,  # C  Status (OPEN/CLOSED)
    "assigned_to": 3,  # D  AssignedTo
    "created_by": 4,  # E  CreatedBy
    "created": 5,  # F  CreationDate
    "last_updated": 6,  # G  LastUpdatedAt
    "priority": 7,  # H  Priority
    "labels": 8,  # I  Labels
    "latest_comment": 9,  # J  LatestCommentPreview
    "issue_source": 15,  # P  project / Issue Source
    "module": 19,  # T  project / Module
    "smartsheet_action_id": 28,  # AC project / SmartSheet Action ID
    "project_status": 31,  # AF project / Status (promotion status)
    "repository": 25,  # Z  project / Repository
}

# Issue Statuses: 0-based fallback index of the "Smart Sheet Action ID" column
# (col O). The loader prefers detecting it by header, this is the fallback.
ISSUE_STATUS_ACTION_ID_COL = 14

# Header matchers used to resolve column indices by name (robust to the sheet
# columns shifting between exports). mode: 'exact' (full header match) or
# 'suffix' (project-prefixed columns like ".../ Status"). All comparisons are
# done on lower-cased, trimmed headers.
GITHUB_COL_MATCHERS = {
    "issue_id": ("exact", "issueid"),
    "title": ("exact", "title"),
    "status": ("exact", "status"),
    "assigned_to": ("exact", "assignedto"),
    "created_by": ("exact", "createdby"),
    "created": ("exact", "creationdate"),
    "last_updated": ("exact", "lastupdatedat"),
    "priority": ("exact", "priority"),
    "labels": ("exact", "labels"),
    "latest_comment": ("exact", "latestcommentpreview"),
    "issue_source": ("suffix", "/ issue source"),
    "module": ("suffix", "/ module"),
    "repository": ("suffix", "/ repository"),
    "smartsheet_action_id": ("suffix", "/ smartsheet action id"),
    "project_status": ("suffix", "/ status"),
}

SMARTSHEET_COL_MATCHERS = {
    "action_id": ("exact", "action id"),
    "title": ("exact", "action title (brief)"),
    "description": ("contains", "action description"),
    "cycle": ("exact", "cycle"),
    "application": ("exact", "application"),
    "assigned_to": ("exact", "assigned to"),
    "stakeholders": ("exact", "stakeholders"),
    "target_date": ("exact", "target date"),
    "ntt_category": ("exact", "ntt category"),
    "priority": ("exact", "priority"),
    "status": ("exact", "status"),
    "solution": ("exact", "solution"),
    "comments": ("exact", "comments"),
    "created_by": ("exact", "created by"),
    "created": ("exact", "created"),
    "modified_by": ("exact", "modified by"),
    "modified": ("exact", "modified"),
    "smartsheet_action_id": ("suffix", "/ smartsheet action id"),
    "github_title": ("suffix", "/ title"),
}

SMARTSHEET_COLS = {
    "action_id": 0,  # A  Action ID
    "title": 1,  # B  Action Title (Brief)
    "description": 2,  # C  Action Description & Example Document Numbers
    "cycle": 3,  # D  Cycle
    "application": 5,  # F  Application
    "assigned_to": 10,  # K  Assigned To
    "stakeholders": 11,  # L  Stakeholders
    "target_date": 12,  # M  Target Date
    "ntt_category": 13,  # N  NTT Category
    "priority": 14,  # O  Priority
    "status": 15,  # P  Status
    "solution": 16,  # Q  Solution
    "comments": 19,  # T  Comments
    "created_by": 20,  # U  Created By
    "created": 21,  # V  Created
    "modified_by": 22,  # W  Modified By
    "modified": 23,  # X  Modified
    "smartsheet_action_id": 28,  # AC project / SmartSheet Action ID (github link)
    "github_title": 34,  # AI project / Title (github issue title when linked)
}


def _clean(value: Any) -> Optional[str]:
    """Normalize a cell value into a trimmed string or None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    s = str(value).strip()
    return s if s else None


def _row_to_dict(row: tuple, colmap: dict[str, int]) -> dict[str, Optional[str]]:
    out: dict[str, Optional[str]] = {}
    for field, idx in colmap.items():
        out[field] = _clean(row[idx]) if idx < len(row) else None
    return out


def _resolve_columns(
    header: tuple, matchers: dict[str, tuple[str, str]], fallback: dict[str, int]
) -> dict[str, int]:
    """Resolve field -> column index by matching header names, with a static
    fallback per field so the loader degrades gracefully if a header is renamed."""
    norm = [str(h).strip().lower() if h is not None else "" for h in header]
    resolved = dict(fallback)
    for field, (mode, pattern) in matchers.items():
        for i, h in enumerate(norm):
            if not h:
                continue
            if (
                (mode == "exact" and h == pattern)
                or (mode == "suffix" and h.endswith(pattern))
                or (mode == "contains" and pattern in h)
            ):
                resolved[field] = i
                break
    return resolved


class WorkbookData:
    """Parsed contents of the tracker workbook."""

    def __init__(
        self,
        github_rows: list[dict],
        smartsheet_rows: list[dict],
        issue_status_rows: list[dict],
        last_refreshed: Optional[str],
        source_path: str,
    ) -> None:
        self.github_rows = github_rows
        self.smartsheet_rows = smartsheet_rows
        # Rows of the 'Issue Statuses' sheet: the business-maintained mapping of
        # Git Issue ID -> Smart Sheet Action ID (the two literal columns).
        self.issue_status_rows = issue_status_rows
        self.last_refreshed = last_refreshed
        self.source_path = source_path
        self.loaded_at = datetime.now().isoformat(sep=" ", timespec="seconds")


def _extract_last_refreshed(wb) -> Optional[str]:
    """Read the 'Last Refreshed: ...' marker from the Issue Statuses sheet."""
    if "Issue Statuses" not in wb.sheetnames:
        return None
    ws = wb["Issue Statuses"]
    for cell in ws[1]:
        text = _clean(cell.value)
        if text and text.lower().startswith("last refreshed"):
            return text.split(":", 1)[1].strip() if ":" in text else text
    return None


def load_workbook_data(path: str | Path) -> WorkbookData:
    """Load the tracker workbook and return normalized row dicts."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Workbook not found: {path}")

    wb = openpyxl.load_workbook(path, data_only=True, keep_vba=True, read_only=True)

    github_rows: list[dict] = []
    if "GitHub Export" in wb.sheetnames:
        ws = wb["GitHub Export"]
        header = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())
        cols = _resolve_columns(header, GITHUB_COL_MATCHERS, GITHUB_COLS)
        for row in ws.iter_rows(min_row=2, values_only=True):
            if row is None or all(c is None for c in row):
                continue
            rec = _row_to_dict(row, cols)
            # Count every GitHub Export row that has an IssueID. The business-
            # maintained "Issue Statuses" sheet is the authoritative universe, so
            # we do NOT drop rows by title (that would silently miss tracked
            # issues whose title merely reads like a test, e.g. "Test Issue").
            if rec.get("issue_id"):
                github_rows.append(rec)

    smartsheet_rows: list[dict] = []
    if "Smart Sheet Export" in wb.sheetnames:
        ws = wb["Smart Sheet Export"]
        header = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())
        cols = _resolve_columns(header, SMARTSHEET_COL_MATCHERS, SMARTSHEET_COLS)
        for row in ws.iter_rows(min_row=2, values_only=True):
            if row is None or all(c is None for c in row):
                continue
            rec = _row_to_dict(row, cols)
            if rec.get("action_id"):
                smartsheet_rows.append(rec)

    # Issue Statuses sheet: literal column A (Git Issue ID) and column O
    # (Smart Sheet Action ID). The in-between columns are uncached VLOOKUP
    # formulas (incl. a "Smart Sheet Sub-Status" in col N), so we recompute
    # from GitHub Export / Smart Sheet Export instead of trusting them.
    issue_status_rows: list[dict] = []
    if "Issue Statuses" in wb.sheetnames:
        ws = wb["Issue Statuses"]
        # Resolve the Smart Sheet Action ID column by header (robust to shifts).
        action_col = ISSUE_STATUS_ACTION_ID_COL
        header = next(ws.iter_rows(min_row=2, max_row=2, values_only=True), ())
        for idx, cell in enumerate(header):
            if cell and "action id" in str(cell).strip().lower():
                action_col = idx
                break
        for row in ws.iter_rows(min_row=3, values_only=True):
            if row is None:
                continue
            git_id = _clean(row[0]) if len(row) > 0 else None
            ss_id = _clean(row[action_col]) if len(row) > action_col else None
            if ss_id and ss_id.strip().upper() in {"#N/A", "#REF!", "#VALUE!", "N/A"}:
                ss_id = None  # broken/absent VLOOKUP result
            if git_id:
                issue_status_rows.append(
                    {"git_issue_id": git_id, "smart_sheet_action_id": ss_id}
                )

    last_refreshed = _extract_last_refreshed(wb)
    wb.close()

    return WorkbookData(
        github_rows=github_rows,
        smartsheet_rows=smartsheet_rows,
        issue_status_rows=issue_status_rows,
        last_refreshed=last_refreshed,
        source_path=str(path),
    )
