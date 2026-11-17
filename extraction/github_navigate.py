"""
Navigate the already-running CDP browser to a URL.

Reuses the browser launched by github_login.py (remote debugging on
REMOTE_DEBUG_PORT). Does not touch credentials.

Usage:
    python github_navigate.py [URL]

Defaults to the helloworld issues page.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

from dotenv import load_dotenv

try:
    import websocket  # from websocket-client
except ImportError:
    sys.exit("Missing dependency. Run: pip install -r requirements.txt")


DEFAULT_URL = "https://github.com/Yugal504/helloworld/issues"


def get_ws_url(port: int, timeout: float = 15.0) -> str:
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=2) as resp:
                targets = json.loads(resp.read().decode("utf-8"))
            pages = [t for t in targets if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
            pages.sort(key=lambda t: "github.com" not in (t.get("url") or ""))
            if pages:
                return pages[0]["webSocketDebuggerUrl"]
        except Exception as exc:  # noqa: BLE001
            last_err = exc
        time.sleep(0.5)
    sys.exit(
        f"Could not reach a running browser on port {port}. "
        f"Run github_login.py first. Last error: {last_err}"
    )


class CDP:
    def __init__(self, ws_url: str):
        self.ws = websocket.create_connection(ws_url, max_size=None)
        self._id = 0

    def send(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        msg_id = self._id
        self.ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
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


def main() -> None:
    load_dotenv()
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    port = int(os.getenv("REMOTE_DEBUG_PORT", "9222"))

    client = CDP(get_ws_url(port))
    try:
        client.send("Page.enable")
        client.send("Runtime.enable")
        print(f"Navigating to: {url}")
        client.send("Page.navigate", {"url": url})
        time.sleep(3)
        current = client.eval("window.location.href").get("result", {}).get("value", "")
        title = client.eval("document.title").get("result", {}).get("value", "")
        print("Current URL:", current)
        print("Page title:", title)
    finally:
        client.close()


if __name__ == "__main__":
    main()
