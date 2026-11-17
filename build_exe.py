"""Build the DefectIQ .exe (onedir) and assemble a shareable folder/zip.

Usage (from the project root, using the project venv's Python):

    .venv\\Scripts\\python.exe build_exe.py

Steps:
  1. Run PyInstaller with DefectIQ.spec  -> dist/DefectIQ/DefectIQ.exe
  2. Copy the EXTERNAL runtime files next to the exe:
        .env, script.txt, data/ (workbook)
  3. Zip dist/DefectIQ into dist/DefectIQ_<timestamp>.zip for handoff.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST_DIR = ROOT / "dist" / "DefectIQ"


def run_pyinstaller() -> None:
    print("=" * 70)
    print("[1/3] Running PyInstaller (onedir)...")
    print("=" * 70)
    cmd = [sys.executable, "-m", "PyInstaller", "DefectIQ.spec", "--noconfirm", "--clean"]
    subprocess.run(cmd, cwd=str(ROOT), check=True)


def copy_external_files() -> None:
    print("=" * 70)
    print("[2/3] Copying external runtime files next to the exe...")
    print("=" * 70)
    if not DIST_DIR.exists():
        raise SystemExit(f"Build output not found: {DIST_DIR}")

    # Single files that must live beside the exe.
    for name in (".env", "script.txt"):
        src = ROOT / name
        if src.exists():
            shutil.copy2(src, DIST_DIR / name)
            print(f"  + {name}")
        else:
            print(f"  ! {name} missing (skipped)")

    # The data folder (workbook). Ship only the workbook/overrides, not backups.
    data_src = ROOT / "data"
    data_dst = DIST_DIR / "data"
    data_dst.mkdir(parents=True, exist_ok=True)
    shipped = 0
    if data_src.exists():
        for f in data_src.iterdir():
            if f.is_file() and f.suffix.lower() in (".xlsm", ".xlsx", ".json"):
                shutil.copy2(f, data_dst / f.name)
                shipped += 1
                print(f"  + data/{f.name}")
    if shipped == 0:
        print("  ! no workbook found in data/ (the BA team must provide one)")

    # Pre-create the runtime output folders so first run is clean.
    for d in ("logs", "downloads", "exports"):
        (DIST_DIR / d).mkdir(parents=True, exist_ok=True)


def zip_dist() -> Path:
    print("=" * 70)
    print("[3/3] Zipping the shareable folder...")
    print("=" * 70)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    base = ROOT / "dist" / f"DefectIQ_{stamp}"
    archive = shutil.make_archive(str(base), "zip", root_dir=str(DIST_DIR.parent), base_dir="DefectIQ")
    return Path(archive)


def main() -> None:
    run_pyinstaller()
    copy_external_files()
    archive = zip_dist()
    print("\n" + "=" * 70)
    print("BUILD COMPLETE")
    print(f"  Folder : {DIST_DIR}")
    print(f"  Zip    : {archive}")
    print("  Run    : dist\\DefectIQ\\DefectIQ.exe")
    print("=" * 70)


if __name__ == "__main__":
    main()
