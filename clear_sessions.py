"""Back up the configured automation browser profile before changing accounts."""

import argparse
import socket
from datetime import datetime
from pathlib import Path

from dotenv import dotenv_values


_ROOT = Path(__file__).resolve().parent


def _browser_running(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def reset_sessions(profile_dir: Path, port: int, dry_run: bool = False) -> Path | None:
    if profile_dir.is_symlink():
        raise ValueError("Refusing to reset a symbolic-link profile directory.")
    profile = profile_dir.expanduser().resolve()
    if profile in {_ROOT, Path.home().resolve(), Path(profile.anchor)} or profile in _ROOT.parents:
        raise ValueError("Refusing to reset a home, project, or root directory.")
    if profile.name.lower() == "user data":
        raise ValueError("Refusing to reset a standard personal browser profile.")
    if not profile.exists():
        print(f"No saved automation sessions found at {profile}.")
        return None
    if not profile.is_dir() or not any(
        (profile / marker).exists() for marker in ("Local State", "Default", "DevToolsActivePort")
    ):
        raise ValueError("Configured path does not look like an automation browser profile.")
    if _browser_running(port):
        raise RuntimeError(
            f"Port {port} is in use. Stop the service and close its automation browser, then retry."
        )
    backup = profile.with_name(f"{profile.name}_backup_{datetime.now():%Y%m%d_%H%M%S_%f}")
    if dry_run:
        print(f"Would move automation profile: {profile}")
        print(f"Backup destination: {backup}")
        return backup
    try:
        profile.rename(backup)
    except OSError as exc:
        raise RuntimeError(
            "Could not back up the profile. Close the automation browser and check folder permissions."
        ) from exc
    print(f"Saved sessions moved to: {backup}")
    print("The next service run will create a fresh browser profile for GitHub and Smartsheet.")
    return backup


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Preview the reset without moving any files.")
    args = parser.parse_args()
    settings = dotenv_values(_ROOT / ".env")
    profile = Path(settings.get("CHROME_PROFILE_DIR") or str(Path.home() / "github_login_profile"))
    if not profile.is_absolute():
        profile = _ROOT / profile
    try:
        reset_sessions(profile, int(settings.get("REMOTE_DEBUG_PORT") or "9222"), args.dry_run)
    except (ValueError, RuntimeError) as exc:
        parser.exit(1, f"Session reset failed: {exc}\n")


if __name__ == "__main__":
    main()