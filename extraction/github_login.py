"""
GitHub login automation over the Chrome DevTools Protocol (CDP).

Follows this project's design (see requirements.txt / .env): no WebDriver /
chromedriver is used, because corporate group policy blocks the drivers. We
launch a Chrome/Edge binary with --remote-debugging-port and drive it over a
websocket.

Steps performed:
  1. Launch the browser and open https://github.com/login
  2. Fill the username field  (#login_field) from GITHUB_USERNAME
  3. Fill the password field  (#password)     from GITHUB_PASSWORD
  4. Click the "Sign in" button (input[name="commit"])

Usage:
    python github_login.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

try:
    import websocket  # from websocket-client
except ImportError:
    sys.exit("Missing dependency. Run: pip install -r requirements.txt")


_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = _ROOT / ".env"
load_dotenv(_ENV_PATH)

LOGIN_URL = os.getenv("GITHUB_LOGIN_URL", "https://github.com/login").strip()


def find_browser(explicit: str) -> str:
    """Resolve a browser executable: BROWSER_PATH -> Edge -> CHROME_PATH."""
    if explicit and Path(explicit).exists():
        return explicit

    # Installed Microsoft Edge (common corporate default).
    edge_candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for path in edge_candidates:
        if Path(path).exists():
            return path

    # Portable Chrome fallback from .env.
    chrome = os.getenv("CHROME_PATH", "")
    if chrome and Path(chrome).exists():
        return chrome

    # Last resort: whatever is on PATH.
    for name in ("msedge", "chrome", "chrome.exe"):
        found = shutil.which(name)
        if found:
            return found

    sys.exit(
        "No browser found. Set BROWSER_PATH or CHROME_PATH in .env to a valid "
        "Chrome/Edge executable."
    )


def launch_browser(
    binary: str, port: int, profile_dir: str, start_url: str = "about:blank"
) -> subprocess.Popen:
    args = [
        binary,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
        start_url,
    ]
    print(f"Launching: {binary}")
    return subprocess.Popen(args)


def wait_browser_down(port: int, timeout: float = 20.0) -> bool:
    """Wait until the remote-debugging endpoint stops responding (browser gone).

    Used between services so a fresh browser instance can bind the port cleanly.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1):
                pass  # still up
        except Exception:  # noqa: BLE001
            return True  # endpoint refused -> browser is down
        time.sleep(0.5)
    return False


def get_ws_url(port: int, timeout: float = 30.0) -> str:
    """Poll the CDP HTTP endpoint for the *browser-level* websocket URL.

    Connecting at the browser level (rather than to a specific page tab) lets us
    create and own a dedicated target, which avoids 'connection aborted' errors
    when a pre-existing tab gets detached on navigation.
    """
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2) as resp:
                info = json.loads(resp.read().decode("utf-8"))
            ws = info.get("webSocketDebuggerUrl")
            if ws:
                return ws
        except Exception as exc:  # noqa: BLE001
            last_err = exc
        time.sleep(0.5)
    sys.exit(f"Could not connect to browser on port {port}. Last error: {last_err}")


class CDP:
    """Minimal synchronous CDP client that owns its own page target."""

    def __init__(self, ws_url: str, create_target: bool = True):
        """Connect at the browser level and attach to a single page target.

        create_target=True  -> create a brand-new tab and drive that.
        create_target=False -> attach to the existing (single) tab, so no extra
                               blank tab is opened. Falls back to creating one if
                               no page target exists yet.
        """
        self.ws = websocket.create_connection(ws_url, max_size=None)
        self._id = 0
        self.session_id = None
        self.target_id = None

        if not create_target:
            targets = self.send("Target.getTargets").get("targetInfos", [])
            pages = [t for t in targets if t.get("type") == "page"]
            if pages:
                self.target_id = pages[0]["targetId"]

        if self.target_id is None:
            self.target_id = self.send("Target.createTarget", {"url": "about:blank"})["targetId"]

        self.session_id = self.send(
            "Target.attachToTarget", {"targetId": self.target_id, "flatten": True}
        )["sessionId"]

    def send(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        msg_id = self._id
        msg = {"id": msg_id, "method": method, "params": params or {}}
        if self.session_id:
            msg["sessionId"] = self.session_id
        self.ws.send(json.dumps(msg))
        # Read until we get the matching response (skip events).
        while True:
            data = json.loads(self.ws.recv())
            if data.get("id") == msg_id:
                if "error" in data:
                    raise RuntimeError(f"{method} failed: {data['error']}")
                return data.get("result", {})

    def eval(self, expression: str) -> dict:
        return self.send(
            "Runtime.evaluate",
            {"expression": expression, "awaitPromise": True, "returnByValue": True},
        )

    def close(self):
        try:
            self.ws.close()
        except Exception:  # noqa: BLE001
            pass

    def close_browser(self):
        """Close the entire browser (browser-level command, no session id)."""
        try:
            self._id += 1
            self.ws.send(json.dumps({"id": self._id, "method": "Browser.close"}))
            time.sleep(0.5)
        except Exception:  # noqa: BLE001
            pass
        self.close()


def js_wait_and_fill(selector: str, value: str) -> str:
    """JS snippet that waits for an element, then sets its value natively."""
    safe_value = json.dumps(value)
    safe_selector = json.dumps(selector)
    return f"""
    (async () => {{
        const sel = {safe_selector};
        const deadline = Date.now() + 15000;
        let el = null;
        while (Date.now() < deadline) {{
            el = document.querySelector(sel);
            if (el) break;
            await new Promise(r => setTimeout(r, 200));
        }}
        if (!el) return "NOT_FOUND:" + sel;
        el.focus();
        const setter = Object.getOwnPropertyDescriptor(
            window.HTMLInputElement.prototype, "value").set;
        setter.call(el, {safe_value});
        el.dispatchEvent(new Event("input", {{ bubbles: true }}));
        el.dispatchEvent(new Event("change", {{ bubbles: true }}));
        return "OK:" + sel;
    }})()
    """


def main() -> None:
    load_dotenv(_ENV_PATH)

    username = os.getenv("GITHUB_USERNAME", "").strip()
    password = os.getenv("GITHUB_PASSWORD", "").strip()
    if not username or not password:
        sys.exit("GITHUB_USERNAME / GITHUB_PASSWORD missing in .env")

    port = int(os.getenv("REMOTE_DEBUG_PORT", "9222"))
    profile_dir = os.getenv("CHROME_PROFILE_DIR") or str(Path.home() / "github_login_profile")
    binary = find_browser(os.getenv("BROWSER_PATH", ""))

    Path(profile_dir).mkdir(parents=True, exist_ok=True)

    proc = launch_browser(binary, port, profile_dir)
    ws_url = get_ws_url(port)
    client = CDP(ws_url)

    try:
        client.send("Page.enable")
        client.send("Runtime.enable")

        # Make sure we're on the login page (the launched tab may have been blank).
        client.send("Page.navigate", {"url": LOGIN_URL})
        time.sleep(2.5)

        # Step 2: username
        res = client.eval(js_wait_and_fill("#login_field", username))
        print("Username field:", res.get("result", {}).get("value"))

        # Step 3: password
        res = client.eval(js_wait_and_fill("#password", password))
        print("Password field:", res.get("result", {}).get("value"))

        # Step 4: click Sign in
        res = client.eval(
            """
            (() => {
                const btn = document.querySelector('input[name="commit"]')
                    || document.querySelector('.js-sign-in-button');
                if (!btn) return "NO_BUTTON";
                btn.click();
                return "CLICKED";
            })()
            """
        )
        print("Sign in button:", res.get("result", {}).get("value"))

        time.sleep(3)
        url = client.eval("window.location.href").get("result", {}).get("value", "")
        print("Current URL:", url)
        if "/login" in url:
            print(
                "Still on login page. If 2FA/MFA, CAPTCHA, or a device-verification "
                "step is required, complete it manually in the open browser window."
            )
        else:
            print("Login submitted. Browser left open.")
    finally:
        client.close()
        # Leave the browser process running so you can see the result / finish MFA.
        _ = proc


if __name__ == "__main__":
    main()
