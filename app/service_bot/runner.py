"""Service Bot runner: orchestrates extraction, write-back and refresh.

In the Excel-based MVP the workbook is the source of truth, so a run simply
re-reads it and refreshes the consolidated dataset. If live GitHub/Smartsheet
credentials are configured, the bot first extracts fresh data and writes it
back into the workbook before refreshing.
"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Optional

import openpyxl

from ..config import Settings, get_settings
from ..data_loader import GITHUB_COLS, SMARTSHEET_COLS
from .github_extractor import ExtractionDisabled, extract_github_issues
from .smartsheet_extractor import extract_smartsheet_rows


def _log(settings: Settings, message: str) -> None:
    with open(settings.execution_log_path, "a", encoding="utf-8") as fh:
        fh.write(f"{datetime.now().isoformat(timespec='seconds')} SERVICEBOT {message}\n")


def _write_sheet(ws, rows: list[dict], colmap: dict[str, int], header_row: int = 1) -> None:
    """Overwrite data rows of a worksheet from normalized dicts."""
    # Clear existing data region (keep header).
    for r in range(ws.max_row, header_row, -1):
        for c in range(1, ws.max_column + 1):
            ws.cell(row=r, column=c).value = None
    # Write new rows.
    for i, rec in enumerate(rows, start=header_row + 1):
        for field, idx in colmap.items():
            ws.cell(row=i, column=idx + 1).value = rec.get(field)


def write_back_to_workbook(
    settings: Settings, github_rows: list[dict], smartsheet_rows: list[dict]
) -> None:
    """Best-effort write of extracted rows into the workbook export sheets."""
    wb = openpyxl.load_workbook(settings.workbook_path, keep_vba=True)
    if github_rows and "GitHub Export" in wb.sheetnames:
        _write_sheet(wb["GitHub Export"], github_rows, GITHUB_COLS)
    if smartsheet_rows and "Smart Sheet Export" in wb.sheetnames:
        _write_sheet(wb["Smart Sheet Export"], smartsheet_rows, SMARTSHEET_COLS)
    if "Issue Statuses" in wb.sheetnames:
        stamp = datetime.now().strftime("Last Refreshed: %m/%d/%Y %I:%M:%S %p")
        wb["Issue Statuses"].cell(row=1, column=2).value = stamp
    wb.save(settings.workbook_path)


def run_extraction(store, settings: Optional[Settings] = None) -> dict:
    """Execute one extraction + refresh cycle. Returns a status dict."""
    settings = settings or get_settings()
    report = {"github": "skipped", "smartsheet": "skipped", "errors": []}
    github_rows: list[dict] = []
    smartsheet_rows: list[dict] = []

    try:
        github_rows = extract_github_issues(settings)
        report["github"] = f"extracted {len(github_rows)}"
    except ExtractionDisabled:
        report["github"] = "excel-source (live disabled)"
    except Exception as exc:  # connectivity / API error -> logged, non-fatal
        report["errors"].append(f"github: {exc}")
        _log(settings, f"ERROR github extraction: {exc}")

    try:
        smartsheet_rows = extract_smartsheet_rows(settings)
        report["smartsheet"] = f"extracted {len(smartsheet_rows)}"
    except ExtractionDisabled:
        report["smartsheet"] = "excel-source (live disabled)"
    except Exception as exc:
        report["errors"].append(f"smartsheet: {exc}")
        _log(settings, f"ERROR smartsheet extraction: {exc}")

    if github_rows or smartsheet_rows:
        try:
            write_back_to_workbook(settings, github_rows, smartsheet_rows)
            _log(settings, "workbook write-back ok")
        except Exception as exc:
            report["errors"].append(f"write-back: {exc}")
            _log(settings, f"ERROR write-back: {exc}")

    # Always refresh the consolidated dataset from the (possibly updated) workbook.
    refresh_result = store.refresh()
    report["refresh"] = refresh_result
    _log(settings, f"run complete {report}")
    return report


class ServiceBot:
    """Background scheduler that periodically runs extraction + refresh."""

    def __init__(self, store, settings: Optional[Settings] = None) -> None:
        self.store = store
        self.settings = settings or get_settings()
        self._timer: Optional[threading.Timer] = None
        self._stopped = True

    def _tick(self) -> None:
        if self._stopped:
            return
        try:
            run_extraction(self.store, self.settings)
        except Exception as exc:  # pragma: no cover
            _log(self.settings, f"ERROR tick: {exc}")
        self._schedule()

    def _schedule(self) -> None:
        interval = self.settings.service_bot_interval_minutes
        if interval <= 0 or self._stopped:
            return
        self._timer = threading.Timer(interval * 60, self._tick)
        self._timer.daemon = True
        self._timer.start()

    def start(self) -> None:
        if self.settings.service_bot_interval_minutes <= 0:
            _log(self.settings, "scheduler disabled (interval=0); manual refresh only")
            return
        self._stopped = False
        self._schedule()
        _log(self.settings, f"scheduler started ({self.settings.service_bot_interval_minutes}m)")

    def stop(self) -> None:
        self._stopped = True
        if self._timer:
            self._timer.cancel()
