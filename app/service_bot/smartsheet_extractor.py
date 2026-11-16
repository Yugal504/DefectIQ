"""Smartsheet extractor (BRD 5.1.2).

Pulls customer-reported defect rows from the configured Smartsheet via the
Smartsheet REST API. Disabled by default (Excel-based MVP). Set
SMARTSHEET_ACCESS_TOKEN / SMARTSHEET_SHEET_ID to enable live extraction.
"""
from __future__ import annotations

import requests

from ..config import Settings
from .github_extractor import ExtractionDisabled

SMARTSHEET_API = "https://api.smartsheet.com/2.0"

# Maps Smartsheet column titles -> normalized field names used downstream.
COLUMN_MAP = {
    "Action ID": "action_id",
    "Action Title (Brief)": "title",
    "Action Description & Example Document Numbers": "description",
    "Cycle": "cycle",
    "Application": "application",
    "Assigned To": "assigned_to",
    "NTT Category": "ntt_category",
    "Priority": "priority",
    "Status": "status",
    "Solution": "solution",
    "Comments": "comments",
    "Created By": "created_by",
    "Created": "created",
    "Modified By": "modified_by",
    "Modified": "modified",
}


def extract_smartsheet_rows(settings: Settings) -> list[dict]:
    if not settings.smartsheet_live_enabled:
        raise ExtractionDisabled("Smartsheet live extraction is not configured.")

    headers = {"Authorization": f"Bearer {settings.smartsheet_token}"}
    url = f"{SMARTSHEET_API}/sheets/{settings.smartsheet_sheet_id}"
    resp = requests.get(url, headers=headers, params={"level": 1}, timeout=60)
    resp.raise_for_status()
    sheet = resp.json()

    # Column id -> normalized field name.
    col_field: dict[int, str] = {}
    for col in sheet.get("columns", []):
        field = COLUMN_MAP.get(col.get("title"))
        if field:
            col_field[col["id"]] = field

    rows: list[dict] = []
    for row in sheet.get("rows", []):
        rec: dict = {v: None for v in COLUMN_MAP.values()}
        for cell in row.get("cells", []):
            field = col_field.get(cell.get("columnId"))
            if field:
                val = cell.get("displayValue", cell.get("value"))
                rec[field] = None if val is None else str(val).strip()
        if rec.get("action_id"):
            rows.append(rec)
    return rows
