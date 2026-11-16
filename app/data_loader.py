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
    "project_status": 30,  # AE project / Status (promotion status)
    "repository": 25,  # Z  project / Repository
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
    "github_title": 33,  # AH project / Title (github issue title when linked)
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


def _is_placeholder_github(rec: dict) -> bool:
    """Data cleansing: GitHub titles that are obvious test/placeholder records
    and must be excluded. The set is configured via PLACEHOLDER_GITHUB_TITLES."""
    from .config import get_settings

    title = (rec.get("title") or "").strip().lower()
    return title in get_settings().placeholder_github_titles


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
        for row in ws.iter_rows(min_row=2, values_only=True):
            if row is None or all(c is None for c in row):
                continue
            rec = _row_to_dict(row, GITHUB_COLS)
            if rec.get("issue_id") and not _is_placeholder_github(rec):
                github_rows.append(rec)

    smartsheet_rows: list[dict] = []
    if "Smart Sheet Export" in wb.sheetnames:
        ws = wb["Smart Sheet Export"]
        for row in ws.iter_rows(min_row=2, values_only=True):
            if row is None or all(c is None for c in row):
                continue
            rec = _row_to_dict(row, SMARTSHEET_COLS)
            if rec.get("action_id"):
                smartsheet_rows.append(rec)

    # Issue Statuses sheet: literal columns A (Git Issue ID) and N (Smart Sheet
    # Action ID). The other columns are uncached formulas, so we recompute them.
    issue_status_rows: list[dict] = []
    if "Issue Statuses" in wb.sheetnames:
        ws = wb["Issue Statuses"]
        for row in ws.iter_rows(min_row=3, values_only=True):
            if row is None:
                continue
            git_id = _clean(row[0]) if len(row) > 0 else None
            ss_id = _clean(row[13]) if len(row) > 13 else None
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
