"""
Stop the Defect Management Agent (run.py) started by Service 4.

Use this when the agent was left running in the background (e.g. a previous
`python main.py` was killed before Ctrl+C, or run.py was started separately).

It kills:
  * whatever process is listening on AGENT_URL's port (default 127.0.0.1:8000), and
  * any python.exe whose command line runs run.py.

Run:
    python stop_agent.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from urllib.parse import urlparse

from dotenv import load_dotenv


def _kill(pid: int) -> None:
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)


def main() -> None:
    load_dotenv()
    url = os.getenv("AGENT_URL", "http://127.0.0.1:8000")
    port = urlparse(url).port or 8000

    killed = set()

    # 1) Kill whatever is listening on the app port.
    ps = (
        "Get-NetTCPConnection -LocalPort {p} -State Listen -ErrorAction SilentlyContinue "
        "| Select-Object -ExpandProperty OwningProcess"
    ).format(p=port)
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True
    ).stdout
    for line in out.splitlines():
        line = line.strip()
        if line.isdigit():
            _kill(int(line))
            killed.add(line)

    # 2) Kill any python.exe running run.py.
    ps2 = (
        "Get-CimInstance Win32_Process -Filter \"name='python.exe'\" "
        "| Where-Object { $_.CommandLine -like '*run.py*' } "
        "| Select-Object -ExpandProperty ProcessId"
    )
    out2 = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps2], capture_output=True, text=True
    ).stdout
    for line in out2.splitlines():
        line = line.strip()
        if line.isdigit():
            _kill(int(line))
            killed.add(line)

    if killed:
        print(f"Stopped agent process(es): {', '.join(sorted(killed))}")
    else:
        print(f"No agent process found (nothing on port {port} and no run.py).")


if __name__ == "__main__":
    main()
