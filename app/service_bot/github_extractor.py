"""GitHub extractor (BRD 5.1.1).

Pulls defect issues from the configured repository via the GitHub REST API.
Disabled by default: the Excel-based MVP reads the pre-exported workbook. Set
GITHUB_TOKEN / GITHUB_OWNER / GITHUB_REPO_NAME to enable live extraction.
"""
from __future__ import annotations

import time
from typing import Optional

import requests

from ..config import Settings

GITHUB_API = "https://api.github.com"


class ExtractionDisabled(RuntimeError):
    """Raised when live extraction is requested but not configured."""


def extract_github_issues(settings: Settings, max_pages: int = 20) -> list[dict]:
    """Return issue dicts aligned to the GitHub Export schema.

    Handles pagination, rate limits (retry on 403/429 with backoff) and
    connectivity errors (BRD 5.1.4 / risk mitigation).
    """
    if not settings.github_live_enabled:
        raise ExtractionDisabled("GitHub live extraction is not configured.")

    headers = {
        "Authorization": f"Bearer {settings.github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    owner, repo = settings.github_owner, settings.github_repo_name
    issues: list[dict] = []
    page = 1
    while page <= max_pages:
        url = f"{GITHUB_API}/repos/{owner}/{repo}/issues"
        params = {"state": "all", "per_page": 100, "page": page}
        resp = _get_with_retry(url, headers, params)
        batch = resp.json()
        if not batch:
            break
        for it in batch:
            if "pull_request" in it:  # skip PRs; keep only issues
                continue
            issues.append(_map_issue(it))
        page += 1
    return issues


def _get_with_retry(url: str, headers: dict, params: dict, retries: int = 4):
    last_exc: Optional[Exception] = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            if resp.status_code in (403, 429):
                reset = resp.headers.get("X-RateLimit-Reset")
                wait = max(2 ** attempt, 5)
                if reset:
                    wait = max(wait, int(reset) - int(time.time()) + 1)
                time.sleep(min(wait, 60))
                continue
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:  # connectivity
            last_exc = exc
            time.sleep(2 ** attempt)
    raise RuntimeError(f"GitHub request failed after {retries} retries: {last_exc}")


def _map_issue(it: dict) -> dict:
    labels = ", ".join(lbl.get("name", "") for lbl in it.get("labels", []))
    assignees = ", ".join(a.get("login", "") for a in it.get("assignees", []))
    return {
        "issue_id": str(it.get("number")),
        "title": it.get("title"),
        "status": (it.get("state") or "").upper(),
        "assigned_to": assignees or (it.get("assignee") or {}).get("login"),
        "created_by": (it.get("user") or {}).get("login"),
        "created": it.get("created_at"),
        "last_updated": it.get("updated_at"),
        "priority": None,  # from project fields when available
        "labels": labels,
        "latest_comment": None,
        "issue_source": None,
        "module": None,
        "smartsheet_action_id": None,
        "project_status": None,
        "repository": it.get("repository_url", "").replace(f"{GITHUB_API}/repos/", ""),
    }
