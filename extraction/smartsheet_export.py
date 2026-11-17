"""
Smartsheet sheet export over the Chrome DevTools Protocol (CDP).

Opens the configured sheet (SMARTSHEET_SHEET_URL / SMARTSHEET_SHEET_NAME in the
workspace SMARTSHEET_WORKSPACE), then drives the sheet menu:

    kebab (More options)  ->  Export  ->  Microsoft Excel

and waits for the .xlsx download to land in SMARTSHEET_DOWNLOAD_PATH.

The Export submenu only opens on a *trusted* hover, so we drive a real mouse
move via Input.dispatchMouseEvent (synthetic DOM mouse events are ignored by
Smartsheet's menu library).

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

KEBAB_SIG = "M11.2 5.2"  # 'd' prefix of the vertical 3-dot (More options) icon.


def _ev(client: CDP, expr: str):
    return client.eval(expr).get("result", {}).get("value")


# --- real mouse input (needed for the hover-activated Export submenu) --------
def _mouse_move(client: CDP, x: int, y: int) -> None:
    client.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y, "buttons": 0})


def _mouse_click(client: CDP, x: int, y: int) -> None:
    _mouse_move(client, x, y)
    client.send("Input.dispatchMouseEvent",
                {"type": "mousePressed", "x": x, "y": y, "button": "left", "buttons": 1, "clickCount": 1})
    client.send("Input.dispatchMouseEvent",
                {"type": "mouseReleased", "x": x, "y": y, "button": "left", "buttons": 0, "clickCount": 1})


def _menuitem_center(client: CDP, text: str):
    js = f"""
    (() => {{
      const w = {json.dumps(text.lower())};
      const e = [...document.querySelectorAll('[role="menuitem"]')]
        .find(el => el.offsetParent !== null && (el.textContent||'').trim().toLowerCase() === w);
      if (!e) return null;
      const r = e.getBoundingClientRect();
      return JSON.stringify({{x: Math.round(r.left + r.width/2), y: Math.round(r.top + r.height/2)}});
    }})()
    """
    v = _ev(client, js)
    return json.loads(v) if v else None


def _menu_has(client: CDP, text: str) -> bool:
    return bool(_ev(client, f"""
        Array.from(document.querySelectorAll('[role="menuitem"]'))
          .some(e => e.offsetParent !== null && (e.textContent||'').trim() === {json.dumps(text)})
    """))


def _click_kebab_rank(client: CDP, rank: int) -> str:
    js = f"""
    (() => {{
      const sig = {json.dumps(KEBAB_SIG)};
      const arr = [];
      for (const svg of document.querySelectorAll('svg')) {{
        const p = svg.querySelector('path'); if (!p) continue;
        if (!(p.getAttribute('d')||'').startsWith(sig)) continue;
        const r = svg.getBoundingClientRect(); if (r.width === 0) continue;
        arr.push([r.top, svg]);
      }}
      arr.sort((a, b) => a[0] - b[0]);
      const pick = arr[{rank}];
      if (!pick) return 'NO_KEBAB';
      (pick[1].closest('button,[role="button"],span') || pick[1]).click();
      return 'CLICKED@' + Math.round(pick[0]);
    }})()
    """
    return _ev(client, js)


def _escape(client: CDP) -> None:
    _ev(client, "document.body.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))")
    time.sleep(0.4)


def _wait_for_kebab(client: CDP, timeout: int = 30) -> bool:
    """Poll until the sheet toolbar (kebab 'More options' icon) has rendered."""
    js = f"""
    Array.from(document.querySelectorAll('svg')).some(s => {{
      const p = s.querySelector('path');
      return p && (p.getAttribute('d')||'').startsWith({json.dumps(KEBAB_SIG)})
             && s.getBoundingClientRect().width > 0;
    }})
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _ev(client, js):
            return True
        time.sleep(1)
    return False


def _open_sheet_menu(client: CDP) -> bool:
    """Open the sheet-level More-options menu (not the workspace one)."""
    for rank in (1, 0, 2, 3):
        res = _click_kebab_rank(client, rank)
        if res == "NO_KEBAB":
            continue
        time.sleep(1.2)
        # The sheet menu is identified by having both Export and Sheet properties.
        if _menu_has(client, "Export") and _menu_has(client, "Sheet properties"):
            print(f"Sheet menu opened via kebab rank {rank} ({res}).")
            return True
        _escape(client)
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

    # Wait for the grid toolbar to actually render (title alone is unreliable).
    if not _wait_for_kebab(client, timeout=30):
        print("Sheet toolbar did not render in time.")
        return None
    title = _ev(client, "document.title")
    print(f"Sheet loaded: {title}")

    if not _open_sheet_menu(client):
        print("Could not open the sheet More-options menu.")
        return None

    # Reveal the Export submenu via a *trusted* hover. A single static mouse
    # move can land before the item is interactive, so we jiggle (approach from
    # the side) and poll until 'Microsoft Excel' appears.
    exp = _menuitem_center(client, "Export")
    if not exp:
        print("Export menu item not found.")
        return None

    submenu_open = False
    for _ in range(12):
        exp = _menuitem_center(client, "Export") or exp
        _mouse_move(client, exp["x"] - 60, exp["y"])   # approach from the left
        time.sleep(0.1)
        _mouse_move(client, exp["x"], exp["y"])        # move onto the item
        time.sleep(0.5)
        if _menu_has(client, "Microsoft Excel"):
            submenu_open = True
            break
    if not submenu_open:
        print("'Microsoft Excel' option not found in Export submenu.")
        return None

    xlsx_center = _menuitem_center(client, "Microsoft Excel")
    if not xlsx_center:
        print("'Microsoft Excel' option not found in Export submenu.")
        return None

    before = _existing_xlsx(download_dir)
    print("Clicking 'Microsoft Excel'...")
    # Approach the submenu item from the side to keep the flyout open, then click.
    _mouse_move(client, xlsx_center["x"] - 20, xlsx_center["y"])
    time.sleep(0.2)
    _mouse_click(client, xlsx_center["x"], xlsx_center["y"])

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
