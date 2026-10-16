"""Request bodies the API accepts."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)


class PasswordChange(BaseModel):
    current: str = Field(max_length=200)
    new: str = Field(min_length=10, max_length=200)


class UserCreate(BaseModel):
    email: str = Field(max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    name: str = Field(min_length=1, max_length=150)
    role: str = Field(pattern=r"^(admin|dispatcher|viewer)$")
    password: str = Field(min_length=10, max_length=200)


class UserUpdate(BaseModel):
    role: str | None = Field(default=None, pattern=r"^(admin|dispatcher|viewer)$")
    active: bool | None = None


class PlanRequest(BaseModel):
    seconds: float = Field(default=30, ge=1, le=300)
    rounds: int | None = Field(default=None, ge=1, le=200_000)
    seed: int = 1
    lookahead: bool = False
    # Start from the last plan and charge for moving a job to another truck, so a
    # re-plan only changes instructions already sent when that is worth it.
    stable: bool = True


class RuleRequest(BaseModel):
    """A rule without its id; the server assigns one."""

    kind: str
    resource_id: str | None = None
    team_id: str | None = None
    job_id: str | None = None
    site_id: str | None = None
    customer: str | None = None
    window: dict[str, datetime] | None = None
    strength: str = "hard"
    penalty_minor: int = 0
    source_text: str = Field(default="Rule form", max_length=2000)


class LockRequest(BaseModel):
    job_id: str
    team_id: str


class FreezeRequest(BaseModel):
    run_id: str
    hours: int = Field(ge=1, le=168)


class InterpretRequest(BaseModel):
    text: str = Field(min_length=2, max_length=1000)


class WhatIfRequest(BaseModel):
    kind: str
    # "repair": the least change to the current plan (instant, exact for that plan);
    # "replan": what a fresh re-plan might add (an estimate, tens of seconds).
    method: Literal["repair", "replan"] = "repair"
    job: str | None = None
    team: str | None = None
    start: datetime | None = None
    end: datetime | None = None


class RollRequest(BaseModel):
    run_id: str | None = None  # default: the latest finished plan
    hours: int = Field(default=24, ge=1, le=168)


class WindowRequest(BaseModel):
    start: datetime
    days: int = Field(ge=1, le=7)
