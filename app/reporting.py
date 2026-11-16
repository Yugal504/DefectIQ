"""Report generation and Excel export (BRD 5.4.4 / Module 4)."""
from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

import openpyxl
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from .models import ConsolidatedDefect

# Columns for the consolidated export (BRD 5.2.2).
CONSOLIDATED_COLUMNS = [
    ("customer_defect_id", "Customer Defect ID"),
    ("github_issue_id", "GitHub Issue ID"),
    ("defect_title", "Defect Title"),
    ("customer_status", "Customer Status"),
    ("github_status", "GitHub Status"),
    ("consolidated_status", "Consolidated Status"),
    ("assigned_developer", "Assigned Developer"),
    ("priority", "Priority"),
    ("created_date", "Created Date"),
    ("last_updated", "Last Updated"),
    ("development_progress", "Development Progress"),
    ("source_availability", "Source Availability"),
    ("github_url", "GitHub URL"),
    ("data_validation_status", "Data Validation Status"),
]

_HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
_HEADER_FONT = Font(color="FFFFFF", bold=True)


def _autosize(ws) -> None:
    for col in range(1, ws.max_column + 1):
        letter = get_column_letter(col)
        width = 12
        for row in range(1, min(ws.max_row, 200) + 1):
            v = ws.cell(row=row, column=col).value
            if v is not None:
                width = max(width, min(60, len(str(v)) + 2))
        ws.column_dimensions[letter].width = width


def _style_header(ws) -> None:
    for cell in ws[1]:
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
    ws.freeze_panes = "A2"


def build_consolidated_xlsx(defects: Iterable[ConsolidatedDefect], title: str = "Issue Statuses") -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = title[:31]
    ws.append([label for _, label in CONSOLIDATED_COLUMNS])
    for d in defects:
        ws.append([getattr(d, field) for field, _ in CONSOLIDATED_COLUMNS])
    _style_header(ws)
    _autosize(ws)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_kpi_xlsx(kpis: dict) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "KPI Summary"
    ws.append(["KPI", "Value"])
    labels = {
        "total_in_smartsheet": "Total Defects in Smartsheet",
        "total_in_github": "Total Defects in GitHub",
        "issue_statuses_count": "Issue Statuses Count",
        "matched_defects": "Matched Defects",
        "missing_in_github": "Missing in GitHub",
        "linked_to_github": "Linked to GitHub",
        "not_linked_to_github": "Not Linked to GitHub",
        "open_defects": "Open Defects",
        "in_progress": "In Progress",
        "closed_defects": "Closed Defects",
        "unassigned_defects": "Unassigned Defects",
        "duplicates": "Duplicates",
        "requires_review": "Requires Review",
    }
    for key, label in labels.items():
        ws.append([label, kpis.get(key)])
    ws.append(["Last Refreshed", kpis.get("last_refreshed")])
    ws.append(["Reconciled At", kpis.get("reconciled_at")])
    ws.append(["Report Generated", datetime.now().isoformat(sep=" ", timespec="seconds")])
    _style_header(ws)
    _autosize(ws)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def extract_source_sheet(workbook_path: str | Path, sheet_name: str) -> Optional[bytes]:
    """Copy a single worksheet from the source workbook into a new xlsx."""
    wb = openpyxl.load_workbook(workbook_path, data_only=True, read_only=True)
    if sheet_name not in wb.sheetnames:
        wb.close()
        return None
    src = wb[sheet_name]
    out = openpyxl.Workbook()
    dst = out.active
    dst.title = sheet_name[:31]
    for row in src.iter_rows(values_only=True):
        dst.append(list(row))
    wb.close()
    _style_header(dst)
    buf = io.BytesIO()
    out.save(buf)
    return buf.getvalue()
