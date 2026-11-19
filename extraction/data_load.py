"""
Data load service.

Loads the freshly-downloaded source files into the master Cockpit tracker
workbook, then archives the sources:

  1. Open the master workbook (data/Cockpit_Issue_Tracker.xlsm by default).
  2. Read the GitHub CSV and merge its rows into the 'GitHub Export' sheet,
     keyed on IssueID (append new, skip duplicates, update changed rows).
  3. Read the Smartsheet Excel and merge its rows into the 'Smart Sheet Export'
     sheet, keyed on Action ID (same upsert behaviour).
  4. Archive both source files by appending a date_time stamp (moved into an
     'archive' subfolder of each source folder).

The merge is controlled by LOAD_MODE (upsert | append | replace) in .env, with
upsert as the default so existing master data is preserved.

A timestamped backup of the master workbook is taken before any change.
Columns are matched by normalized header name (case/space/punctuation
insensitive), so 'Github Export' vs 'GitHub Export' and 'AssignedTo' vs
'Assigned To' all line up.

Run standalone:
    python data_load.py
"""

from __future__ import annotations

import csv
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from openpyxl import load_workbook

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = _PROJECT_ROOT / ".env"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _norm(name) -> str:
    """Normalize a header/sheet name: lowercase, alphanumerics only."""
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


def _resolve_path(value: str, default: str) -> Path:
    """Resolve a configured path (absolute, or relative to this project root)."""
    raw = (value or "").strip() or default
    p = Path(raw)
    return p if p.is_absolute() else (_PROJECT_ROOT / p).resolve()


def _find_master() -> Path | None:
    """Locate the master workbook the Defect Management Agent reads.

    Configured via MASTER_EXCEL_PATH (absolute, or relative to this project).
    Defaults to the sibling "Defect Management Agent" workbook so a single run
    refreshes the data the dashboard serves.
    """
    master = _resolve_path(
        os.getenv("MASTER_EXCEL_PATH", ""),
        r"data\Cockpit_Issue_Tracker.xlsm",
    )
    return master if master.exists() else None


def _newest(folder: Path, pattern: str) -> Path | None:
    """Return the most recently modified file in `folder` matching `pattern`."""
    if not folder.exists():
        return None
    cands = [p for p in folder.glob(pattern) if "archive" not in p.parts]
    return max(cands, key=lambda p: p.stat().st_mtime) if cands else None


def _find_sheet(wb, *norm_names):
    wanted = set(norm_names)
    for ws in wb.worksheets:
        if _norm(ws.title) in wanted:
            return ws
    return None


def _read_csv(path: Path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        return [], []
    return rows[0], rows[1:]


def _read_xlsx(path: Path, sheet: str | None = None):
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb[sheet] if sheet and sheet in wb.sheetnames else wb.worksheets[0]
    header, data = [], []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            header = list(row)
        elif any(c is not None and str(c).strip() != "" for c in row):
            data.append(list(row))
    wb.close()
    return header, data


def _coerce_csv(value):
    """CSV values are all strings; convert pure numbers so IDs/counts are numeric."""
    if value is None:
        return None
    s = str(value).strip()
    if s == "":
        return None
    if re.fullmatch(r"[+-]?\d+", s):
        try:
            return int(s)
        except ValueError:
            return s
    if re.fullmatch(r"[+-]?\d*\.\d+", s):
        try:
            return float(s)
        except ValueError:
            return s
    return s


def _load_rows(ws, src_header, src_rows, label: str, coerce, mode: str) -> int:
    """Map source columns to the sheet header and write rows.

    mode="replace": clear the sheet's existing data rows first, so the full
    export snapshot replaces the old data. mode="append": add rows below the
    existing data (no deduplication).
    """
    _, mapping, matched, unmatched = _build_mapping(ws, src_header)

    existing = max(ws.max_row - 1, 0)  # minus header row
    if mode == "replace" and existing > 0:
        ws.delete_rows(2, existing)
        start_row = 2
    else:
        start_row = ws.max_row + 1 if existing > 0 else 2

    print(f"  [{label}] mode={mode}; matched {len(matched)}/{len(src_header)} source "
          f"columns; existing rows={existing}; writing {len(src_rows)} rows at row {start_row}.")
    if unmatched:
        print(f"  [{label}] unmapped source columns (left out): {unmatched}")

    for r, s_row in enumerate(src_rows):
        for s_idx, m_col in mapping.items():
            val = s_row[s_idx] if s_idx < len(s_row) else None
            ws.cell(row=start_row + r, column=m_col, value=coerce(val) if coerce else val)
    return len(src_rows)


def _cmp(value) -> str:
    """Normalize a cell value for equality comparison (duplicate detection)."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def _build_mapping(ws, src_header):
    """Return (master_map, mapping src_idx->master_col, matched, unmatched)."""
    master_header = [c.value for c in ws[1]]
    master_map = {}
    for i, h in enumerate(master_header, start=1):
        key = _norm(h)
        if key and key not in master_map:
            master_map[key] = i

    mapping, matched, unmatched = {}, [], []
    for s_idx, s_h in enumerate(src_header):
        m_col = master_map.get(_norm(s_h))
        if m_col:
            mapping[s_idx] = m_col
            matched.append(s_h)
        else:
            unmatched.append(s_h)
    return master_map, mapping, matched, unmatched


def _upsert_rows(ws, src_header, src_rows, label: str, coerce, key_name: str) -> int:
    """Merge source rows into the sheet keyed on `key_name`:

      * key not present in the master  -> append as a new row,
      * key present and all mapped values identical -> skip (duplicate),
      * key present but a mapped value changed -> update that row in place.

    Existing master rows are never deleted. Falls back to append-only if the key
    column is missing from either the source or the master (so no data is lost).
    """
    master_map, mapping, matched, unmatched = _build_mapping(ws, src_header)

    key_norm = _norm(key_name)
    key_m_col = master_map.get(key_norm)
    key_s_idx = next((i for i, h in enumerate(src_header) if _norm(h) == key_norm), None)

    if key_m_col is None or key_s_idx is None:
        where = "master" if key_m_col is None else "source"
        print(f"  [{label}] merge key '{key_name}' not found in the {where} header; "
              f"falling back to append (no rows removed).")
        return _load_rows(ws, src_header, src_rows, label, coerce, "append")

    # Index existing master rows by their key value (first occurrence wins).
    index: dict[str, int] = {}
    for r in range(2, ws.max_row + 1):
        kv = _cmp(ws.cell(row=r, column=key_m_col).value)
        if kv and kv not in index:
            index[kv] = r

    def _new_values(s_row):
        out = {}
        for s_idx, m_col in mapping.items():
            raw = s_row[s_idx] if s_idx < len(s_row) else None
            out[m_col] = coerce(raw) if coerce else raw
        return out

    appended = updated = unchanged = blank = 0
    next_row = ws.max_row + 1
    for s_row in src_rows:
        raw_key = s_row[key_s_idx] if key_s_idx < len(s_row) else None
        kv = _cmp(coerce(raw_key) if coerce else raw_key)
        new_vals = _new_values(s_row)

        if not kv:
            # No usable key -> cannot dedup; append so nothing is lost.
            for m_col, val in new_vals.items():
                ws.cell(row=next_row, column=m_col, value=val)
            next_row += 1
            appended += 1
            blank += 1
            continue

        existing_row = index.get(kv)
        if existing_row is not None:
            changed = any(
                _cmp(ws.cell(row=existing_row, column=m_col).value) != _cmp(val)
                for m_col, val in new_vals.items()
            )
            if changed:
                for m_col, val in new_vals.items():
                    ws.cell(row=existing_row, column=m_col, value=val)
                updated += 1
            else:
                unchanged += 1
        else:
            for m_col, val in new_vals.items():
                ws.cell(row=next_row, column=m_col, value=val)
            index[kv] = next_row
            next_row += 1
            appended += 1

    extra = f" (incl. {blank} without a key)" if blank else ""
    print(f"  [{label}] upsert on '{key_name}': appended {appended}{extra}, "
          f"updated {updated}, unchanged {unchanged}; "
          f"matched {len(matched)}/{len(src_header)} source columns.")
    if unmatched:
        print(f"  [{label}] unmapped source columns (left out): {unmatched}")
    return appended + updated


def _archive(path: Path, stamp: str) -> Path:
    archive_dir = path.parent / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    dest = archive_dir / f"{path.stem}_{stamp}{path.suffix}"
    shutil.move(str(path), str(dest))
    return dest


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------
def data_load_service() -> bool:
    load_dotenv(_ENV_PATH)
    project_root = _PROJECT_ROOT
    downloads = project_root / "downloads"

    gh_dir = _resolve_path(os.getenv("GITHUB_DOWNLOAD_PATH", ""), r"downloads\github")
    ss_dir = _resolve_path(os.getenv("SMARTSHEET_DOWNLOAD_PATH", ""), r"downloads\smartsheet")
    # How to merge the exports into the master sheets:
    #   upsert  = append new rows, skip duplicates, update changed rows (default)
    #   append  = add every source row below existing data (no dedup)
    #   replace = clear the sheet then write the fresh snapshot
    mode = os.getenv("LOAD_MODE", "upsert").strip().lower()
    if mode not in ("upsert", "append", "replace"):
        mode = "upsert"
    # Unique business key per sheet, used for upsert dedup/update.
    gh_key = (os.getenv("GITHUB_MERGE_KEY", "").strip()
              or os.getenv("GITHUB_UNIQUE_KEY", "").strip() or "IssueID")
    ss_key = os.getenv("SMARTSHEET_MERGE_KEY", "").strip() or "Action ID"
    ss_sheet_name = os.getenv("SMARTSHEET_SHEET_NAME", "").strip() or None

    master = _find_master()
    # The GitHub script always writes this exact filename; still take the newest.
    gh_csv = _newest(gh_dir, "github_issues_export.csv") or _newest(gh_dir, "*.csv")
    ss_xlsx = _newest(ss_dir, "*.xlsx")

    print("=" * 70)
    print("SERVICE 3 - Data load: load sources into the master tracker")
    print("=" * 70)

    if not master or not master.exists():
        print("Master workbook not found. Set MASTER_EXCEL_PATH in .env to the "
              "Defect Management Agent workbook (Cockpit_Issue_Tracker.xlsx/.xlsm).")
        return False
    print(f"Master workbook: {master}")

    have_gh = bool(gh_csv and gh_csv.exists())
    have_ss = bool(ss_xlsx and ss_xlsx.exists())
    if not have_gh and not have_ss:
        print("No source files found (already archived?). Nothing to load.")
        return False

    # Read source data up front.
    gh_header, gh_rows = _read_csv(gh_csv) if have_gh else ([], [])
    ss_header, ss_rows = _read_xlsx(ss_xlsx, ss_sheet_name) if have_ss else ([], [])
    if have_gh:
        print(f"GitHub CSV: {len(gh_rows)} rows, {len(gh_header)} columns.")
    if have_ss:
        print(f"Smartsheet xlsx: {len(ss_rows)} rows, {len(ss_header)} columns.")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Safety backup of the master before any modification. Stored next to the
    # master (in an "Archive" subfolder) so it is easy to roll back.
    archive_dir = master.parent / "Archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    backup = archive_dir / f"{master.stem}_BACKUP_{stamp}{master.suffix}"
    shutil.copy2(master, backup)
    print(f"Backup created: {backup}")

    keep_vba = master.suffix.lower() == ".xlsm"
    if keep_vba:
        print("  Note: saving the .xlsm via openpyxl preserves macros and the raw "
              "data sheets but rebuilds the file; pre-built PivotTable sheets are "
              "dropped (the dashboard recomputes its own charts/KPIs). A backup was "
              "saved above.")
    wb = load_workbook(master, keep_vba=keep_vba)

    gh_ws = _find_sheet(wb, "githubexport") if have_gh else None
    ss_ws = _find_sheet(wb, "smartsheetexport") if have_ss else None

    if have_gh and gh_ws is None:
        print("Could not find a 'Github Export' sheet in the master; skipping GitHub load.")
    if have_ss and ss_ws is None:
        print("Could not find a 'Smartsheet Export' sheet in the master; skipping Smartsheet load.")

    try:
        if gh_ws is not None:
            if mode == "upsert":
                _upsert_rows(gh_ws, gh_header, gh_rows, "Github Export", _coerce_csv, gh_key)
            else:
                _load_rows(gh_ws, gh_header, gh_rows, "Github Export", _coerce_csv, mode)
        if ss_ws is not None:
            if mode == "upsert":
                _upsert_rows(ss_ws, ss_header, ss_rows, "Smartsheet Export", None, ss_key)
            else:
                _load_rows(ss_ws, ss_header, ss_rows, "Smartsheet Export", None, mode)
        # Stamp the "Last Refreshed" marker (Issue Statuses sheet, B1) so the
        # dashboard's "Data as of" reflects THIS data load. Matches the cell the
        # dashboard reads (app/data_loader._extract_last_refreshed).
        is_ws = _find_sheet(wb, "issuestatuses")
        if is_ws is not None:
            refreshed = datetime.now().strftime("Last Refreshed: %m/%d/%Y %I:%M:%S %p")
            is_ws.cell(row=1, column=2, value=refreshed)
            print(f"  Stamped '{refreshed}' on Issue Statuses!B1.")
        wb.save(master)
        print(f"Master workbook saved: {master.name}")
    except Exception:
        wb.close()
        print("Load failed; restoring master from backup.")
        shutil.copy2(backup, master)
        raise
    finally:
        wb.close()

    # Archive the source files (append date_time stamp).
    if have_gh and gh_ws is not None:
        print(f"Archived GitHub CSV   -> {_archive(gh_csv, stamp)}")
    if have_ss and ss_ws is not None:
        print(f"Archived Smartsheet   -> {_archive(ss_xlsx, stamp)}")

    print("Data load complete.")
    return True


def main() -> None:
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:  # noqa: BLE001
        pass
    load_dotenv(_ENV_PATH)
    data_load_service()


if __name__ == "__main__":
    main()
