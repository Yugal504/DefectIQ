"""Write dashboard UPDATE/DELETE operations back into the master workbook.

Scope (per product decision): we only UPDATE and DELETE rows in the two source
export sheets - "GitHub Export" (key: IssueID) and "Smart Sheet Export" (key:
Action ID). We never INSERT. The "Issue Statuses" sheet is intentionally left
alone: it is driven by VLOOKUPs/macros that recompute from those two sheets.

Excel COM automation (pywin32) is used instead of openpyxl because openpyxl
rewrites the whole .xlsm and DROPS every PivotTable sheet. COM drives Excel
itself, so PivotTables, macros (VBA) and formulas are all preserved and
recalculated on save.

All operations are serialized by a module lock and each runs in its own Excel
process. If pywin32/Excel is unavailable the functions degrade gracefully
(return a reason) so the dashboard CRUD still works via the overrides store.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional

GH_SHEET = "GitHub Export"
SS_SHEET = "Smart Sheet Export"

# 1-based key columns.
GH_KEY_COL = 1  # IssueID
SS_KEY_COL = 1  # Action ID

# Map ConsolidatedDefect field -> 1-based column in each sheet. Fields not
# present in a sheet are simply skipped for that sheet.
GH_FIELD_COLS = {
    "defect_title": 2,         # Title
    "consolidated_status": 3,  # Status
    "assigned_developer": 4,   # AssignedTo
    "priority": 8,             # Priority
    "module": 20,              # Project ... / Module
}
SS_FIELD_COLS = {
    "defect_title": 2,         # Action Title (Brief)
    "assigned_developer": 11,  # Assigned To
    "priority": 15,            # Priority
    "consolidated_status": 16, # Status
    "description": 20,         # Comments
}

_LOCK = threading.Lock()


def _norm(value) -> str:
    """Normalize a key for comparison (ints like 123 vs '123', '123.0')."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def _find_row(ws, key_col: int, key_val: str) -> int:
    """Return the 1-based row of the first data row whose key matches, else 0.

    Reads the whole key column in one COM call for speed."""
    key = _norm(key_val)
    if not key:
        return 0
    last = ws.Cells(ws.Rows.Count, key_col).End(-4162).Row  # xlUp
    if last < 2:
        return 0
    rng = ws.Range(ws.Cells(2, key_col), ws.Cells(last, key_col))
    values = rng.Value  # tuple of 1-tuples (or scalar if a single row)
    if not isinstance(values, tuple):
        values = ((values,),)
    for idx, row in enumerate(values, start=2):
        cell = row[0] if isinstance(row, tuple) else row
        if _norm(cell) == key:
            return idx
    return 0


def _open_excel():
    import pythoncom  # noqa: WPS433
    import win32com.client as win32  # noqa: WPS433

    pythoncom.CoInitialize()
    app = win32.DispatchEx("Excel.Application")
    app.Visible = False
    app.DisplayAlerts = False
    app.ScreenUpdating = False
    try:
        app.AskToUpdateLinks = False
    except Exception:  # noqa: BLE001
        pass
    return app


def _close_excel(app) -> None:
    import pythoncom  # noqa: WPS433

    try:
        app.Quit()
    except Exception:  # noqa: BLE001
        pass
    try:
        pythoncom.CoUninitialize()
    except Exception:  # noqa: BLE001
        pass


def _apply(workbook_path: Path, github_issue_id, action_id, changes: Optional[dict], op: str) -> dict:
    """Core COM routine. op is 'update' or 'delete'."""
    result = {"op": op, "github": "skipped", "smartsheet": "skipped", "errors": []}
    targets = [
        (GH_SHEET, GH_KEY_COL, github_issue_id, GH_FIELD_COLS, "github"),
        (SS_SHEET, SS_KEY_COL, action_id, SS_FIELD_COLS, "smartsheet"),
    ]
    abs_path = str(Path(workbook_path).resolve())
    with _LOCK:
        app = None
        wb = None
        try:
            app = _open_excel()
            wb = app.Workbooks.Open(abs_path, UpdateLinks=0, ReadOnly=False)
            changed_any = False
            for sheet_name, key_col, key_val, field_cols, label in targets:
                if not _norm(key_val):
                    continue
                try:
                    ws = wb.Worksheets(sheet_name)
                except Exception:  # noqa: BLE001
                    result["errors"].append(f"{label}: sheet '{sheet_name}' not found")
                    continue
                row = _find_row(ws, key_col, key_val)
                if not row:
                    result[label] = "key not found"
                    continue
                if op == "delete":
                    ws.Rows(row).Delete()
                    result[label] = f"deleted row {row}"
                    changed_any = True
                else:  # update
                    applied = []
                    for field, col in field_cols.items():
                        if changes and field in changes:
                            ws.Cells(row, col).Value = changes[field]
                            applied.append(field)
                    result[label] = f"updated row {row} ({', '.join(applied) or 'no mapped fields'})"
                    if applied:
                        changed_any = True
            if changed_any:
                try:
                    app.CalculateFull()
                except Exception:  # noqa: BLE001
                    pass
                try:
                    wb.RefreshAll()
                    app.CalculateUntilAsyncQueriesDone()
                except Exception:  # noqa: BLE001
                    pass
                wb.Save()
            wb.Close(SaveChanges=False)
            wb = None
        except Exception as exc:  # noqa: BLE001
            result["errors"].append(str(exc))
            try:
                if wb is not None:
                    wb.Close(SaveChanges=False)
            except Exception:  # noqa: BLE001
                pass
        finally:
            if app is not None:
                _close_excel(app)
    return result


def available() -> bool:
    try:
        import win32com.client  # noqa: F401,WPS433
        return True
    except Exception:  # noqa: BLE001
        return False


def apply_update(workbook_path, github_issue_id, action_id, changes: dict) -> dict:
    return _apply(Path(workbook_path), github_issue_id, action_id, changes, "update")


def apply_delete(workbook_path, github_issue_id, action_id) -> dict:
    return _apply(Path(workbook_path), github_issue_id, action_id, None, "delete")
