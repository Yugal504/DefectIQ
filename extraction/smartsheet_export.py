"""
Smartsheet sheet export over the Chrome DevTools Protocol (CDP).

Opens the configured sheet (SMARTSHEET_SHEET_URL), then drives the sheet menu:

    org: File -> Export -> Export to Microsoft Excel
    personal: More options -> Export -> Microsoft Excel

and waits for the .xlsx download to land in SMARTSHEET_DOWNLOAD_PATH.

Menu clicks use Input.dispatchMouseEvent for trusted mouse input.

Self-sufficient: if the sheet redirects to login, it logs in first.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from .github_login import CDP, get_ws_url
from .smartsheet_login import smartsheet_login

_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = _ROOT / ".env"
load_dotenv(_ENV_PATH)

def _ev(client: CDP, expr: str):
    return client.eval(expr).get("result", {}).get("value")


def _mouse_move(client: CDP, x: int, y: int) -> None:
    client.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y, "buttons": 0})


def _mouse_click(client: CDP, x: int, y: int) -> None:
    _mouse_move(client, x, y)
    client.send("Input.dispatchMouseEvent",
                {"type": "mousePressed", "x": x, "y": y, "button": "left", "buttons": 1, "clickCount": 1})
    client.send("Input.dispatchMouseEvent",
                {"type": "mouseReleased", "x": x, "y": y, "button": "left", "buttons": 0, "clickCount": 1})


def _menuitem_center(client: CDP, text: str, selector: str = 'td.clsStandardMenuText, [role="menuitem"]'):
    js = f"""
    (() => {{
      const w = {json.dumps(text.lower())};
            const e = [...document.querySelectorAll({json.dumps(selector)})]
                .find(el => {{
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0
                        && getComputedStyle(el).visibility !== 'hidden'
                        && !el.closest('[aria-disabled="true"], [disabled]')
                        && (el.textContent||'').trim().toLowerCase() === w;
                }});
      if (!e) return null;
      const r = e.getBoundingClientRect();
      return JSON.stringify({{x: Math.round(r.left + r.width/2), y: Math.round(r.top + r.height/2)}});
    }})()
    """
    v = _ev(client, js)
    return json.loads(v) if v else None


def _wait_for_menuitem(client: CDP, text: str, timeout: int = 30,
                       selector: str = 'td.clsStandardMenuText, [role="menuitem"]'):
    deadline = time.time() + timeout
    while time.time() < deadline:
        center = _menuitem_center(client, text, selector)
        if center:
            return center
        time.sleep(0.5)
    return None


def _open_personal_sheet_menu(client: CDP) -> bool:
    deadline = time.time() + 30
    while time.time() < deadline:
        for rank in (1, 0, 2, 3):
            clicked = _ev(client, f"""
                (() => {{
                    const icons = [...document.querySelectorAll('svg')]
                        .filter(icon => icon.getBoundingClientRect().width > 0
                            && (icon.querySelector('path')?.getAttribute('d') || '')
                                .startsWith('M11.2 5.2'))
                        .sort((first, second) => first.getBoundingClientRect().top
                            - second.getBoundingClientRect().top);
                    const icon = icons[{rank}];
                    if (!icon) return false;
                    (icon.closest('button,[role="button"],span') || icon).click();
                    return true;
                }})()
            """)
            if not clicked:
                continue
            time.sleep(1)
            if _menuitem_center(client, "Export") and _menuitem_center(client, "Sheet properties"):
                return True
            client.send("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Escape", "code": "Escape", "windowsVirtualKeyCode": 27})
            client.send("Input.dispatchKeyEvent", {"type": "keyUp", "key": "Escape", "code": "Escape", "windowsVirtualKeyCode": 27})
        time.sleep(0.5)
    return False


def _existing_xlsx(folder: Path) -> dict:
    return {p.name: p.stat().st_mtime for p in folder.glob("*.xlsx")}


def _wait_for_download(folder: Path, before: dict, timeout: int) -> Path | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        # A completed .xlsx that is new or newly modified, and not a .crdownload.
        for p in folder.glob("*.xlsx"):
            if p.name not in before or p.stat().st_mtime > before[p.name]:
                # Ensure no partial download is still in progress.
                if not list(folder.glob("*.crdownload")) and p.stat().st_size > 0:
                    time.sleep(1)
                    return p
        time.sleep(1)
    return None


def smartsheet_export(client: CDP, download_dir: Path, timeout: int = 120) -> Path | None:
    """Export the open sheet to Excel and return the downloaded file path."""
    load_dotenv(_ENV_PATH)
    service_type = os.getenv("SERVICE_TYPE", "org").strip().lower()
    if service_type not in {"org", "personal"}:
        raise ValueError("SERVICE_TYPE must be 'org' or 'personal'.")
    sheet_url = os.getenv("SMARTSHEET_SHEET_URL", "").strip()
    if not sheet_url:
        sys.exit("SMARTSHEET_SHEET_URL is missing in .env")

    download_dir.mkdir(parents=True, exist_ok=True)

    # Point downloads at our folder.
    try:
        client.send("Page.setDownloadBehavior",
                    {"behavior": "allow", "downloadPath": str(download_dir)})
    except Exception as exc:  # noqa: BLE001
        print(f"(Could not set download path via CDP: {exc}; using browser default.)")

    print(f"Opening sheet: {sheet_url}")
    client.send("Page.navigate", {"url": sheet_url})
    time.sleep(8)

    # If the sheet bounced to login, authenticate then reopen.
    if "/login" in (_ev(client, "window.location.href") or ""):
        smartsheet_login(
            client,
            os.getenv("SMARTSHEET_USERNAME", "").strip(),
            os.getenv("SMARTSHEET_PASSWORD", "").strip(),
            int(os.getenv("MFA_WAIT_TIMEOUT", "300")),
        )
        client.send("Page.navigate", {"url": sheet_url})
        time.sleep(8)

    print(f"Smartsheet service type: {service_type}")
    menu_steps = (
        ("File", 'span, button, [role="menuitem"]'),
        ("Export", 'td.clsStandardMenuText, [role="menuitem"]'),
        ("Export to Microsoft Excel", 'td.clsStandardMenuText, [role="menuitem"]'),
    )
    if service_type == "personal":
        if not _open_personal_sheet_menu(client):
            print("Could not open the personal sheet More-options menu.")
            return None
        menu_steps = (
            ("Export", '[role="menuitem"]'),
            ("Microsoft Excel", '[role="menuitem"]'),
        )
    before = _existing_xlsx(download_dir)
    for label, selector in menu_steps:
        if service_type == "personal" and label == "Microsoft Excel":
            center = None
            for attempt in range(12):
                export_center = _menuitem_center(client, "Export")
                if export_center:
                    _mouse_move(client, export_center["x"] - 60, export_center["y"])
                    time.sleep(0.1)
                    _mouse_move(client, export_center["x"], export_center["y"])
                time.sleep(0.5)
                center = _menuitem_center(client, label, selector)
                if center:
                    break
        else:
            center = _wait_for_menuitem(client, label, selector=selector)
        if not center:
            print(f"'{label}' menu item did not appear in time.")
            return None
        if service_type == "personal" and label == "Export":
            continue
        print(f"Clicking '{label}'...")
        _mouse_click(client, center["x"], center["y"])

    print("Waiting for the .xlsx download...")
    path = _wait_for_download(download_dir, before, timeout)
    if path:
        print(f"Download complete: {path}  ({path.stat().st_size} bytes)")
    else:
        print(f"No .xlsx detected in {download_dir} within {timeout}s.")
    return path


def main() -> None:
    load_dotenv(_ENV_PATH)
    port = int(os.getenv("REMOTE_DEBUG_PORT", "9222"))
    download_dir = _ROOT / os.getenv("SMARTSHEET_DOWNLOAD_PATH", r"downloads\smartsheet")
    timeout = int(os.getenv("DOWNLOAD_TIMEOUT", "120"))

    client = CDP(get_ws_url(port))
    try:
        client.send("Page.enable")
        client.send("Runtime.enable")
        smartsheet_export(client, download_dir, timeout)
    finally:
        client.close()


if __name__ == "__main__":
    main()
