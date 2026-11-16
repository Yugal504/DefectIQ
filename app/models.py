"""Pydantic models for the API layer."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ConsolidatedDefect(BaseModel):
    """A single reconciled defect record (one row of 'Issue Statuses')."""

    record_id: str = Field(..., description="Stable internal id for CRUD/audit")
    customer_defect_id: Optional[str] = None  # Smart Sheet Action ID
    github_issue_id: Optional[str] = None
    defect_title: Optional[str] = None
    description: Optional[str] = None
    customer_status: Optional[str] = None  # Smartsheet status
    github_status: Optional[str] = None  # GitHub status
    consolidated_status: Optional[str] = None  # Open / In Progress / Closed
    assigned_developer: Optional[str] = None
    priority: Optional[str] = None
    customer_priority: Optional[str] = None
    github_priority: Optional[str] = None
    created_date: Optional[str] = None
    last_updated: Optional[str] = None
    development_progress: Optional[str] = None  # promotion status / project status
    latest_comment: Optional[str] = None
    module: Optional[str] = None
    ntt_category: Optional[str] = None
    labels: Optional[str] = None
    issue_source: Optional[str] = None  # e.g. Exception Triage, Shared Mailbox
    source_availability: Optional[str] = None  # Smartsheet / GitHub / Both
    github_url: Optional[str] = None
    data_validation_status: Optional[str] = None  # Matched/Missing/Duplicate/Requires Review

    # Provenance flags
    is_manual: bool = False  # created via CRUD (not from extraction)
    is_overridden: bool = False  # extracted record modified via CRUD


class DefectCreate(BaseModel):
    customer_defect_id: Optional[str] = None
    github_issue_id: Optional[str] = None
    defect_title: str
    description: Optional[str] = None
    consolidated_status: str = "Open"
    assigned_developer: Optional[str] = None
    priority: Optional[str] = None
    module: Optional[str] = None


class DefectUpdate(BaseModel):
    customer_defect_id: Optional[str] = None
    github_issue_id: Optional[str] = None
    defect_title: Optional[str] = None
    description: Optional[str] = None
    consolidated_status: Optional[str] = None
    customer_status: Optional[str] = None
    github_status: Optional[str] = None
    assigned_developer: Optional[str] = None
    priority: Optional[str] = None
    module: Optional[str] = None


class LoginRequest(BaseModel):
    username: str
    password: str


class ChatRequest(BaseModel):
    message: str
    history: list[dict[str, str]] = Field(default_factory=list)


class ChatResponse(BaseModel):
    reply: str
    data: Optional[dict[str, Any]] = None
    used_llm: bool = False
    refreshed_at: Optional[str] = None
