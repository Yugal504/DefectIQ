"""
Smartsheet login automation over the Chrome DevTools Protocol (CDP).

Smartsheet uses a multi-step login:
  1. Enter work email            (#loginEmail)      from SMARTSHEET_USERNAME
  2. Continue, then choose        "Sign in with email and password"
  3. Enter password              (#loginPassword)   from SMARTSHEET_PASSWORD
  4. Click Sign in               (#signInControl)

Can be run standalone (attaches to a browser already started by main.py /
github_login.py) or imported and called via smartsheet_login(client, ...).

    python smartsheet_login.py
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from .github_login import CDP, get_ws_url, js_wait_and_fill

_ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_ENV_PATH)

LOGIN_URL = os.getenv("SMARTSHEET_LOGIN_URL", "https://app.smartsheet.com/login").strip()


def _eval_value(client: CDP, expr: str):
    return client.eval(expr).get("result", {}).get("value")


def js_wait_and_click(selector: str, timeout_ms: int = 15000) -> str:
    sel = json.dumps(selector)
    return f"""
    (async () => {{
        const sel = {sel};
        const deadline = Date.now() + {timeout_ms};
        let el = null;
        while (Date.now() < deadline) {{
            el = document.querySelector(sel);
            if (el && el.offsetParent !== null && el.getAttribute('aria-disabled') !== 'true') break;
            el = null;
            await new Promise(r => setTimeout(r, 200));
        }}
        if (!el) return "NOT_FOUND:" + sel;
        el.click();
        return "CLICKED:" + sel;
    }})()
    """


def js_click_by_text(texts, timeout_ms: int = 15000) -> str:
    """Click the first visible element whose text matches one of `texts`."""
    needles = json.dumps([t.lower() for t in texts])
    return f"""
    (async () => {{
        const needles = {needles};
        const deadline = Date.now() + {timeout_ms};
        const tags = ['button', 'a', 'div', 'span'];
        while (Date.now() < deadline) {{
            for (const tag of tags) {{
                for (const el of document.querySelectorAll(tag)) {{
                    if (el.offsetParent === null) continue;
                    const txt = (el.textContent || '').trim().toLowerCase();
                    if (!txt) continue;
                    if (needles.some(n => txt === n || txt.includes(n))) {{
                        const target = el.closest('button, a, [role="button"]') || el;
                        target.click();
                        return "CLICKED:" + txt.slice(0, 60);
                    }}
                }}
            }}
            await new Promise(r => setTimeout(r, 200));
        }}
        return "NOT_FOUND";
    }})()
    """


def js_present(selector: str) -> str:
    sel = json.dumps(selector)
    return f"(() => {{ const e = document.querySelector({sel}); return !!(e && e.offsetParent !== null); }})()"


def smartsheet_login(client: CDP, email: str, password: str, mfa_timeout: int = 300) -> str:
    """Perform the full Smartsheet email+password login in the current tab.

    Handles both entry points:
      * Fresh login:  /login with the #loginEmail field.
      * Remembered account: /login/providers (email cached in profile), which
        skips straight to the provider chooser.
    """
    print(f"Navigating to: {LOGIN_URL}")
    client.send("Page.navigate", {"url": LOGIN_URL})
    time.sleep(4)  # SPA needs time to render.

    # If a session already exists, Smartsheet redirects into the app.
    current = _eval_value(client, "window.location.href") or ""
    if "/login" not in current:
        print(f"Already authenticated to Smartsheet. URL: {current}")
        return current

    # Step 1 (only when shown): email. When the account is remembered, Smartsheet
    # jumps to /login/providers and there is no #loginEmail field.
    if _eval_value(client, js_present("#loginEmail")):
        res = _eval_value(client, js_wait_and_fill("#loginEmail", email))
        print("Email field:", res)
        if not str(res).startswith("OK"):
            return f"EMAIL_FIELD_FAILED:{res}"
        _eval_value(client, js_click_by_text(["continue", "next"]))
        time.sleep(2)
    else:
        print("Email field not shown (account remembered); using provider chooser.")

    # Step 2: pick "Sign in with email and password" on the providers page.
    res = _eval_value(client, js_click_by_text(["sign in with email and password"], timeout_ms=12000))
    print("Provider choice:", res)

    # Wait for the password field to appear.
    deadline = time.time() + 20
    while time.time() < deadline:
        if _eval_value(client, js_present("#loginPassword")):
            break
        time.sleep(0.5)

    # Step 3: password.
    res = _eval_value(client, js_wait_and_fill("#loginPassword", password))
    print("Password field:", res)
    if not str(res).startswith("OK"):
        return f"PASSWORD_FIELD_FAILED:{res}"

    # Step 4: Sign in.
    res = _eval_value(client, js_wait_and_click("#signInControl"))
    print("Sign in button:", res)

    # Wait for login to complete (leave /login), allowing time for MFA.
    deadline = time.time() + max(mfa_timeout, 5)
    prompted = False
    while time.time() < deadline:
        url = _eval_value(client, "window.location.href") or ""
        if url and "/login" not in url:
            print(f"Smartsheet login complete. URL: {url}")
            return url
        if not prompted:
            print(
                "Waiting for Smartsheet login. If 2FA/MFA or verification is "
                "required, complete it in the open browser window now..."
            )
            prompted = True
        time.sleep(2)

    return _eval_value(client, "window.location.href") or ""


def main() -> None:
    load_dotenv(_ENV_PATH)
    email = os.getenv("SMARTSHEET_USERNAME", "").strip()
    password = os.getenv("SMARTSHEET_PASSWORD", "").strip()
    if not email or not password:
        sys.exit("SMARTSHEET_USERNAME / SMARTSHEET_PASSWORD missing in .env")

    port = int(os.getenv("REMOTE_DEBUG_PORT", "9222"))
    mfa_timeout = int(os.getenv("MFA_WAIT_TIMEOUT", "300"))

    client = CDP(get_ws_url(port))
    try:
        client.send("Page.enable")
        client.send("Runtime.enable")
        smartsheet_login(client, email, password, mfa_timeout)
    finally:
        client.close()


if __name__ == "__main__":
    main()
