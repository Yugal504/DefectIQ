"""
DefectIQ AI Solution - single entry point.

Run the whole solution with one command:

    python main.py

Four services run in sequence:

  1. GitHub service    : open browser -> log in -> open issues -> export issues
                         to CSV (GITHUB_DOWNLOAD_PATH) -> close.
  2. Smartsheet service: open a NEW browser -> log in -> open the sheet ->
                         export the sheet to Excel (SMARTSHEET_DOWNLOAD_PATH) ->
                         close.
  3. Data load         : load both source files into the master tracker
                         (data/Cockpit_Issue_Tracker.xlsm) the dashboard reads.
  4. Dashboard         : start the FastAPI dashboard + chatbot (run.py) and open
                         the browser at AGENT_URL (127.0.0.1:8000).

The browser services use no WebDriver/chromedriver (blocked by group policy);
everything is driven over the DevTools Protocol. All configuration lives in the
single .env file in this folder - nothing is hardcoded in the Python.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent
_ENV_PATH = _ROOT / ".env"

# Make the extraction package importable when run as "python main.py".
sys.path.insert(0, str(_ROOT))

from extraction.github_login import (
    CDP,
    LOGIN_URL,
    find_browser,
    get_ws_url,
    js_wait_and_fill,
    launch_browser,
    wait_browser_down,
)
from extraction.smartsheet_login import smartsheet_login
from extraction.smartsheet_export import smartsheet_export
from extraction.data_load import data_load_service

try:
    import websocket  # noqa: F401  (ensures dependency is present)
except ImportError:
    sys.exit("Missing dependency. Run: pip install -r requirements.txt")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def issues_url_from_repo(repo_url: str) -> str:
    repo_url = (repo_url or "").strip().rstrip("/")
    if not repo_url:
        sys.exit("GITHUB_REPO_URL is missing in .env")
    return f"{repo_url}/issues"


def owner_repo_from_url(repo_url: str) -> str:
    """Extract 'owner/repo' from a GitHub repo URL (for the export script)."""
    return urlparse((repo_url or "").strip().rstrip("/")).path.strip("/")


def wait_for_login(client: CDP, mfa_timeout: int) -> str:
    """Return the current URL once we leave /login, pausing for MFA if needed."""
    deadline = time.time() + max(mfa_timeout, 5)
    prompted = False
    while time.time() < deadline:
        url = client.eval("window.location.href").get("result", {}).get("value", "")
        if url and "/login" not in url and "/session" not in url:
            return url
        if not prompted:
            print(
                "Waiting for login to complete. If GitHub asks for 2FA/MFA, "
                "a CAPTCHA, or device verification, complete it in the open "
                "browser window now..."
            )
            prompted = True
        time.sleep(2)
    return client.eval("window.location.href").get("result", {}).get("value", "")


def run_issue_export(
    client: CDP,
    token: str,
    script_path: Path,
    download_dir: Path,
    owner_repo: str = "",
) -> Path | None:
    """Inject the PAT and run script.txt in the page to export the CSV.

    The target repository is taken from .env (GITHUB_REPO_URL) and injected into
    the script at runtime, so script.txt holds no hardcoded repository.
    """
    if not script_path.exists():
        sys.exit(f"Export script not found: {script_path}")

    script_js = script_path.read_text(encoding="utf-8")
    if owner_repo:
        # Replace the `const repo = "...";` line so the configured repo is used.
        script_js = re.sub(
            r'const\s+repo\s*=\s*"[^"]*"\s*;',
            f'const repo = {json.dumps(owner_repo)};',
            script_js,
            count=1,
        )
    download_dir.mkdir(parents=True, exist_ok=True)
    try:
        client.send(
            "Page.setDownloadBehavior",
            {"behavior": "allow", "downloadPath": str(download_dir)},
        )
    except Exception as exc:  # noqa: BLE001
        print(f"(Could not set download path via CDP: {exc}; using browser default.)")

    injected = (
        "window.prompt = function() { return " + json.dumps(token) + "; };\n" + script_js
    )

    csv_path = download_dir / "github_issues_export.csv"
    before = csv_path.stat().st_mtime if csv_path.exists() else 0

    print("Running issue export (script.txt) in the page...")
    client.eval(injected)

    deadline = time.time() + 120
    while time.time() < deadline:
        if csv_path.exists() and csv_path.stat().st_mtime > before and csv_path.stat().st_size > 0:
            time.sleep(1)
            print(f"Export complete: {csv_path}  ({csv_path.stat().st_size} bytes)")
            return csv_path
        time.sleep(1)

    print(
        "Export finished running but no CSV was detected in "
        f"{download_dir}. The repo may have no issues, or the token may lack "
        "Issues/Projects read access."
    )
    return None


# ---------------------------------------------------------------------------
# Service 1: GitHub
# ---------------------------------------------------------------------------
def github_service(cfg: dict) -> Path | None:
    print("=" * 70)
    print("SERVICE 1 - GitHub: export issues to CSV")
    print("=" * 70)

    issues_url = issues_url_from_repo(cfg["repo_url"])
    proc = launch_browser(cfg["binary"], cfg["port"], cfg["profile_dir"], LOGIN_URL)
    client = CDP(get_ws_url(cfg["port"]), create_target=False)  # reuse the single tab
    exported = None
    try:
        client.send("Page.enable")
        client.send("Runtime.enable")

        print("\n[1/3] Logging in to GitHub...")
        client.send("Page.navigate", {"url": LOGIN_URL})
        time.sleep(2.5)
        current = client.eval("window.location.href").get("result", {}).get("value", "")
        if "/login" in current:
            client.eval(js_wait_and_fill("#login_field", cfg["gh_user"]))
            client.eval(js_wait_and_fill("#password", cfg["gh_pass"]))
            client.eval(
                """
                (() => {
                    const btn = document.querySelector('input[name="commit"]')
                        || document.querySelector('.js-sign-in-button');
                    if (btn) { btn.click(); return "CLICKED"; }
                    return "NO_BUTTON";
                })()
                """
            )
        else:
            print("Already authenticated (existing session in profile).")

        logged_url = wait_for_login(client, cfg["mfa_timeout"])
        if "/login" in logged_url or "/session" in logged_url:
            print(f"GitHub login did not complete (still at {logged_url}).")
            return None
        print(f"Logged in. Current URL: {logged_url}")

        print(f"\n[2/3] Navigating to issues: {issues_url}")
        client.send("Page.navigate", {"url": issues_url})
        time.sleep(3)
        title = client.eval("document.title").get("result", {}).get("value", "")
        print(f"Page title: {title}")

        print("\n[3/3] Exporting issues to CSV...")
        exported = run_issue_export(
            client,
            cfg["token"],
            cfg["script_path"],
            cfg["gh_download_dir"],
            owner_repo=owner_repo_from_url(cfg["repo_url"]),
        )
    finally:
        print("Closing the GitHub browser...")
        client.close_browser()
        wait_browser_down(cfg["port"])
        _ = proc
    return exported


# ---------------------------------------------------------------------------
# Service 2: Smartsheet
# ---------------------------------------------------------------------------
def smartsheet_service(cfg: dict) -> Path | None:
    print("\n" + "=" * 70)
    print("SERVICE 2 - Smartsheet: export sheet to Excel")
    print("=" * 70)

    if not cfg["ss_user"] or not cfg["ss_pass"]:
        print("SMARTSHEET_USERNAME / SMARTSHEET_PASSWORD missing in .env; skipping.")
        return None

    proc = launch_browser(cfg["binary"], cfg["port"], cfg["profile_dir"], "about:blank")
    client = CDP(get_ws_url(cfg["port"]), create_target=False)  # reuse the single tab
    exported = None
    try:
        client.send("Page.enable")
        client.send("Runtime.enable")

        print("\n[1/2] Logging in to Smartsheet...")
        smartsheet_login(client, cfg["ss_user"], cfg["ss_pass"], cfg["mfa_timeout"])

        print("\n[2/2] Exporting Smartsheet to Excel...")
        exported = smartsheet_export(client, cfg["ss_download_dir"], cfg["download_timeout"])
    finally:
        print("Closing the Smartsheet browser...")
        client.close_browser()
        wait_browser_down(cfg["port"])
        _ = proc
    return exported


# ---------------------------------------------------------------------------
# Service 3: Data load
# ---------------------------------------------------------------------------
def data_load(cfg: dict) -> bool:
    print("\n")
    try:
        return data_load_service()
    except Exception as exc:  # noqa: BLE001
        print(f"Data load failed: {exc}")
        return False


# ---------------------------------------------------------------------------
# Service 4: Dashboard (FastAPI app served by run.py, in this same project)
# ---------------------------------------------------------------------------
def _wait_for_port(host: str, port: int, timeout: int = 60) -> bool:
    """Poll a TCP port until something is listening (server is up)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=2):
                return True
        except OSError:
            time.sleep(1)
    return False


def _terminate_tree(proc: subprocess.Popen) -> None:
    """Kill a process and its children (Windows)."""
    if proc is None:
        return
    try:
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            capture_output=True,
        )
    except Exception:  # noqa: BLE001
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass


def _dashboard_python() -> str:
    """Prefer the project .venv (it has fastapi/uvicorn) over the current
    interpreter, so `python main.py` works even from a bare system Python."""
    venv_py = _ROOT / ".venv" / "Scripts" / "python.exe"
    return str(venv_py) if venv_py.exists() else sys.executable


def _dashboard_browser() -> str:
    """Resolve the browser used to OPEN THE DASHBOARD.

    Corporate Edge is often forced into Internet Explorer (IE) mode for
    local/intranet URLs via an Enterprise-Mode site list policy. The IE
    (Trident) engine does not support CSS custom properties or modern JS, so
    the dashboard renders broken and sign-in does nothing. Chrome is not
    subject to that policy, so prefer Chrome here (override via .env with
    DASHBOARD_BROWSER_PATH). Returns "" to fall back to the OS default.
    """
    explicit = os.getenv("DASHBOARD_BROWSER_PATH", "").strip()
    if explicit and Path(explicit).exists():
        return explicit

    chrome_candidates = [
        os.getenv("CHROME_PATH", "").strip(),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        str(Path(os.getenv("LOCALAPPDATA", "")) / r"Google\Chrome\Application\chrome.exe"),
    ]
    for path in chrome_candidates:
        if path and Path(path).exists():
            return path

    found = shutil.which("chrome") or shutil.which("chrome.exe")
    return found or ""


def dashboard_service(cfg: dict):
    """Start the dashboard (run.py) and open the app. Returns the Popen or None."""
    print("\n" + "=" * 70)
    print("SERVICE 4 - Dashboard: start run.py and open the app")
    print("=" * 70)

    script = _ROOT / "run.py"
    url = cfg["agent_url"]
    if not script.exists():
        print(f"run.py not found in: {_ROOT}")
        return None

    python_exe = _dashboard_python()
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8000

    proc = None
    if _wait_for_port(host, port, timeout=1):
        print(f"An app is already listening on {host}:{port}; reusing it.")
    else:
        print(f"Starting dashboard: \"{python_exe}\" run.py  (cwd={_ROOT})")
        proc = subprocess.Popen([python_exe, "run.py"], cwd=str(_ROOT))
        print(f"Waiting for the app at {url} ...")
        if _wait_for_port(host, port, timeout=60):
            print("App is up.")
        else:
            print(f"App did not respond on {host}:{port} within 60s; opening browser anyway.")

    browser = _dashboard_browser()
    if browser:
        print(f"Opening dashboard in Chrome at {url}\n  ({browser})")
        try:
            subprocess.Popen([browser, "--new-window", url])
            return proc
        except Exception:  # noqa: BLE001
            print("Could not launch Chrome; falling back to the OS default browser.")
    else:
        print(
            "Chrome not found. Opening with the OS default browser.\n"
            "  NOTE: If your Edge opens this page in Internet Explorer (IE) mode\n"
            "  (a blue 'e' icon in the address bar), the dashboard will look\n"
            "  broken and sign-in will not work. Open it in Chrome, or set\n"
            "  DASHBOARD_BROWSER_PATH / CHROME_PATH in .env to a Chrome .exe."
        )

    print(f"Opening browser at {url}")
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001
        pass
    return proc


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:  # noqa: BLE001
        pass

    load_dotenv(_ENV_PATH)

    cfg = {
        "gh_user": os.getenv("GITHUB_USERNAME", "").strip(),
        "gh_pass": os.getenv("GITHUB_PASSWORD", "").strip(),
        "token": os.getenv("GITHUB_TOKEN", "").strip(),
        "repo_url": os.getenv("GITHUB_REPO_URL", "").strip(),
        "ss_user": os.getenv("SMARTSHEET_USERNAME", "").strip(),
        "ss_pass": os.getenv("SMARTSHEET_PASSWORD", "").strip(),
        "port": int(os.getenv("REMOTE_DEBUG_PORT", "9222")),
        "profile_dir": os.getenv("CHROME_PROFILE_DIR") or str(Path.home() / "github_login_profile"),
        "mfa_timeout": int(os.getenv("MFA_WAIT_TIMEOUT", "300")),
        "download_timeout": int(os.getenv("DOWNLOAD_TIMEOUT", "120")),
        "agent_url": os.getenv("AGENT_URL", "http://127.0.0.1:8000"),
    }
    if not cfg["gh_user"] or not cfg["gh_pass"]:
        sys.exit("GITHUB_USERNAME / GITHUB_PASSWORD missing in .env")
    if not cfg["token"]:
        sys.exit("GITHUB_TOKEN missing in .env (required for the export API calls)")

    cfg["script_path"] = _ROOT / os.getenv("SCRIPT_PATH", "script.txt")
    cfg["gh_download_dir"] = _ROOT / os.getenv("GITHUB_DOWNLOAD_PATH", r"downloads\github")
    cfg["ss_download_dir"] = _ROOT / os.getenv("SMARTSHEET_DOWNLOAD_PATH", r"downloads\smartsheet")
    cfg["binary"] = find_browser(os.getenv("BROWSER_PATH", ""))
    Path(cfg["profile_dir"]).mkdir(parents=True, exist_ok=True)

    # --- Service 1: GitHub (open -> export CSV -> close) ---------------------
    csv_file = github_service(cfg)

    # --- Service 2: Smartsheet (fresh browser -> export Excel -> close) ------
    xlsx_file = smartsheet_service(cfg)

    # --- Service 3: Data load (load sources into the master) -----------------
    loaded = data_load(cfg)

    # --- Service 4: Dashboard (FastAPI app) ----------------------------------
    agent_proc = dashboard_service(cfg)

    print("\n" + "=" * 70)
    print("Workflow finished.")
    print(f"  Service 1 GitHub CSV   : {csv_file if csv_file else 'NOT DOWNLOADED'}")
    print(f"  Service 2 Smartsheet   : {xlsx_file if xlsx_file else 'NOT DOWNLOADED'}")
    print(f"  Service 3 Data load    : {'OK' if loaded else 'FAILED/SKIPPED'}")
    print(f"  Service 4 Dashboard    : {'RUNNING' if agent_proc else 'reused/failed - see log'}")
    print("=" * 70)

    # Keep the dashboard in the foreground so Ctrl+C stops it cleanly.
    if agent_proc is not None:
        print(f"\nDashboard is running at {cfg['agent_url']}. Press Ctrl+C to stop it.")
        try:
            agent_proc.wait()
        except KeyboardInterrupt:
            print("\nCtrl+C received - stopping the dashboard...")
            _terminate_tree(agent_proc)
            try:
                agent_proc.wait(timeout=10)
            except Exception:  # noqa: BLE001
                pass
            print("Dashboard stopped.")


if __name__ == "__main__":
    main()
