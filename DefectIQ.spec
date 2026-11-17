# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for DefectIQ (onedir build).

Build:   pyinstaller DefectIQ.spec --noconfirm
Output:  dist/DefectIQ/DefectIQ.exe  (+ _internal/)

Read-only UI assets (frontend/) are bundled INSIDE the app. User-editable and
output files (.env, data/, script.txt, logs/, downloads/) live NEXT TO the exe
and are copied in by build_exe.py after this spec runs.
"""
from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

hiddenimports = []
hiddenimports += collect_submodules("uvicorn")
hiddenimports += collect_submodules("app")
hiddenimports += collect_submodules("extraction")
hiddenimports += collect_submodules("fastapi")
hiddenimports += collect_submodules("starlette")
hiddenimports += ["h11", "anyio", "click", "dotenv", "multipart", "websocket"]
# Excel COM write-back (pywin32).
hiddenimports += ["win32com", "win32com.client", "pythoncom", "pywintypes", "win32api"]

datas = [("frontend", "frontend")]
binaries = []

# Packages that ship data/compiled bits PyInstaller's static analysis can miss.
for pkg in ("openai", "pydantic", "pydantic_core", "openpyxl"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "PyQt5", "PySide2", "notebook"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DefectIQ",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="DefectIQ",
)
