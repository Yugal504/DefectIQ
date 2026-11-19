"""Central configuration, loaded from environment variables / .env file."""
from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# Project root. When frozen by PyInstaller, user-editable/output files (.env,
# data/, logs/, exports/) live NEXT TO the .exe; otherwise it's the parent of
# the "app" package directory.
if getattr(sys, "frozen", False):
    ROOT_DIR = Path(sys.executable).resolve().parent
else:
    ROOT_DIR = Path(__file__).resolve().parent.parent

# Load .env from project root if present (does not override real env vars).
load_dotenv(ROOT_DIR / ".env")


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (ValueError, TypeError):
        return default


# Default demo user directory (username | plaintext password | role | display name).
_DEFAULT_DEMO_USERS = (
    "admin|admin123|Administrator|Administrator;"
    "pm|pm123|Project Manager|Project Manager;"
    "dev|dev123|Developer|Developer;"
    "user|user123|Business User|Business User;"
    "viewer|viewer123|Read-Only User|Read-Only User"
)


def _parse_demo_users(raw: str) -> dict[str, dict]:
    users: dict[str, dict] = {}
    for entry in (raw or "").split(";"):
        entry = entry.strip()
        if not entry:
            continue
        parts = [p.strip() for p in entry.split("|")]
        if len(parts) >= 3 and parts[0] and parts[1]:
            username, password, role = parts[0], parts[1], parts[2]
            name = parts[3] if len(parts) >= 4 and parts[3] else role
            users[username.lower()] = {"password": password, "role": role, "name": name}
    return users


class Settings:
    """Runtime settings resolved from the environment."""

    def __init__(self) -> None:
        # --- Data source ---
        wb = os.getenv("DEFECT_WORKBOOK_PATH", "data/Cockpit_Issue_Tracker.xlsm")
        wb_path = Path(wb)
        self.workbook_path: Path = wb_path if wb_path.is_absolute() else ROOT_DIR / wb_path
        self.github_repo: str = os.getenv("GITHUB_REPO", "CE-Neurostack/celanese-cockpit")

        # --- Azure OpenAI ---
        self.azure_openai_endpoint: str = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
        self.azure_openai_api_key: str = os.getenv("AZURE_OPENAI_API_KEY", "").strip()
        self.azure_openai_deployment: str = os.getenv("AZURE_OPENAI_DEPLOYMENT", "").strip()
        self.azure_openai_api_version: str = os.getenv(
            "AZURE_OPENAI_API_VERSION", "2024-08-01-preview"
        ).strip()

        # --- Live extraction (optional) ---
        self.github_token: str = os.getenv("GITHUB_TOKEN", "").strip()
        self.github_owner: str = os.getenv("GITHUB_OWNER", "").strip()
        self.github_repo_name: str = os.getenv("GITHUB_REPO_NAME", "").strip()
        self.smartsheet_token: str = os.getenv("SMARTSHEET_ACCESS_TOKEN", "").strip()
        self.smartsheet_sheet_id: str = os.getenv("SMARTSHEET_SHEET_ID", "").strip()

        # --- Service Bot schedule ---
        try:
            self.service_bot_interval_minutes: int = int(
                os.getenv("SERVICE_BOT_INTERVAL_MINUTES", "0")
            )
        except ValueError:
            self.service_bot_interval_minutes = 0

        # --- Server bind address ---
        self.host: str = os.getenv("HOST", "127.0.0.1").strip()
        self.port: int = _int("PORT", 8000)

        # --- App metadata ---
        self.app_title: str = os.getenv("APP_TITLE", "Defect Management Agentic AI").strip()
        self.app_version: str = os.getenv("APP_VERSION", "1.0.0").strip()

        # --- Excel write-back (dashboard UPDATE/DELETE -> source export sheets) ---
        # When enabled, edits/deletes in the dashboard are written back to the
        # "GitHub Export" and "Smart Sheet Export" sheets of the workbook via
        # Excel COM (preserves PivotTables, macros and formulas). Requires
        # Microsoft Excel + pywin32 on the machine running the service.
        self.excel_writeback_enabled: bool = _bool(os.getenv("EXCEL_WRITEBACK_ENABLED"), True)

        # --- Pagination ---
        self.default_page_size: int = _int("DEFAULT_PAGE_SIZE", 25)
        self.max_page_size: int = _int("MAX_PAGE_SIZE", 500)

        # --- Security ---
        self.app_secret_key: str = os.getenv("APP_SECRET_KEY", "change-me-in-production")
        self.auth_password_salt: str = os.getenv("AUTH_PASSWORD_SALT", "dm-salt::")
        self.session_ttl_hours: int = _int("SESSION_TTL_HOURS", 8)
        self.demo_users: dict[str, dict] = _parse_demo_users(
            os.getenv("DEMO_USERS", "") or _DEFAULT_DEMO_USERS
        )

        # --- Derived paths ---
        self.data_dir: Path = self.workbook_path.parent
        self.logs_dir: Path = ROOT_DIR / "logs"
        self.exports_dir: Path = ROOT_DIR / "exports"
        self.overrides_path: Path = self.data_dir / "defect_overrides.json"
        self.audit_log_path: Path = self.logs_dir / "audit.log"
        self.execution_log_path: Path = self.logs_dir / "execution.log"

        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.exports_dir.mkdir(parents=True, exist_ok=True)

    @property
    def session_ttl_seconds(self) -> int:
        return self.session_ttl_hours * 60 * 60

    @property
    def azure_openai_enabled(self) -> bool:
        return bool(
            self.azure_openai_endpoint
            and self.azure_openai_api_key
            and self.azure_openai_deployment
        )

    @property
    def github_live_enabled(self) -> bool:
        return bool(self.github_token and self.github_owner and self.github_repo_name)

    @property
    def smartsheet_live_enabled(self) -> bool:
        return bool(self.smartsheet_token and self.smartsheet_sheet_id)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
