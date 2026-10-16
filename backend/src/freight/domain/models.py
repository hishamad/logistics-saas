from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Identifier = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[\w.-]+$")]
Equipment = Literal["dry_van", "flatbed"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Window(Model):
    start: datetime
    end: datetime

    @field_validator("start", "end")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("An explicit timezone is required")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.end < self.start:
            raise ValueError("Window end precedes its start")
        return self


class Site(Model):
    id: Identifier
    name: str = Field(min_length=1, max_length=150)
    name_ar: str = Field(default="", max_length=150)


class Resource(Model):
    id: Identifier
    name: str = Field(min_length=1, max_length=150)
    kind: Literal["tractor", "trailer", "driver"]
    site_id: Identifier
    availability: Window
    unavailable: tuple[Window, ...] = Field(default=(), max_length=100)
    equipment: Equipment | None = None
    capacity_kg: int | None = Field(default=None, gt=0, le=100_000)
    confirmed_at: datetime

    @field_validator("confirmed_at")
    @classmethod
    def aware_confirmation(cls, value: datetime) -> datetime:
        return Window.timezone_required(value)

    @model_validator(mode="after")
    def trailer_details(self) -> Self:
        if self.kind == "trailer" and (self.equipment is None or self.capacity_kg is None):
            raise ValueError("Trailer equipment and capacity are required")
        return self


class Team(Model):
    id: Identifier
    name: str = Field(min_length=1, max_length=150)
    tractor_id: Identifier
    trailer_id: Identifier
    driver_id: Identifier
    # Home depot when the team is currently elsewhere; defaults to the tractor's site.
    home_site_id: Identifier | None = None

    @property
    def resource_ids(self) -> tuple[str, str, str]:
        return self.tractor_id, self.trailer_id, self.driver_id


class Job(Model):
    id: Identifier
    reference: str = Field(min_length=1, max_length=100)
    customer: str = Field(min_length=1, max_length=150)
    pickup_site_id: Identifier
    delivery_site_id: Identifier
    pickup_window: Window
    delivery_window: Window
    delivery_window_kind: Literal["service_start", "completion"] = "completion"
    loading_minutes: int = Field(default=30, ge=0, le=480)
    unloading_minutes: int = Field(default=30, ge=0, le=480)
    turnaround_minutes: int = Field(default=15, ge=0, le=480)
    equipment: Equipment
    weight_kg: int = Field(gt=0, le=100_000)
    priority: int = Field(default=1, ge=1, le=3)
    state: Literal["confirmed", "offered", "cancelled"] = "confirmed"
    revenue_minor: int | None = Field(default=None, ge=0)
    # When the order became known; replay and rolling planning only see known work.
    known_at: datetime | None = None

    @field_validator("known_at")
    @classmethod
    def aware_known_at(cls, value: datetime | None) -> datetime | None:
        return Window.timezone_required(value) if value else None


class Lane(Model):
    from_site_id: Identifier
    to_site_id: Identifier
    distance_m: int = Field(ge=0, le=10_000_000)
    duration_minutes: int = Field(ge=0, le=10_000)
    source: str = Field(default="synthetic", min_length=1, max_length=200)

    @model_validator(mode="after")
    def physical_movement(self) -> Self:
        if self.from_site_id == self.to_site_id:
            if self.distance_m or self.duration_minutes:
                raise ValueError("A same-site lane must have zero distance and duration")
        elif self.distance_m == 0 or self.duration_minutes == 0:
            raise ValueError(
                "Travel between distinct sites requires positive distance and duration"
            )
        return self


class CostProfile(Model):
    currency: Literal["SAR"] = "SAR"
    distance_minor_per_km: Decimal | None = Field(default=None, ge=0, le=100_000, decimal_places=2)
    duty_minor_per_hour: Decimal | None = Field(default=None, ge=0, le=100_000, decimal_places=2)
    includes_fuel: Literal[True] = True
    exclusions: tuple[str, ...] = ("Fixed overhead", "Taxes", "Unmodeled tolls")

    @property
    def complete(self) -> bool:
        return self.distance_minor_per_km is not None and self.duty_minor_per_hour is not None


class Rule(Model):
    id: Identifier
    kind: Literal[
        "resource_unavailable", "required_end", "customer_eligibility", "preferred_assignment"
    ]
    resource_id: str | None = None
    team_id: str | None = None
    job_id: str | None = None
    site_id: str | None = None
    customer: str | None = None
    window: Window | None = None
    strength: Literal["hard", "soft"] = "hard"
    penalty_minor: int = Field(default=0, ge=0, le=1_000_000)
    source_text: str = Field(default="Manual rule", max_length=2000)

    @model_validator(mode="after")
    def required_fields(self) -> Self:
        required = {
            "resource_unavailable": ("resource_id", "window"),
            "required_end": ("team_id", "site_id", "window"),
            "customer_eligibility": ("team_id", "customer"),
            "preferred_assignment": ("team_id", "job_id"),
        }
        for field in required[self.kind]:
            if getattr(self, field) is None:
                raise ValueError(f"{self.kind} requires {field}")
        for field in ("resource_id", "team_id", "job_id", "site_id", "customer", "window"):
            if field not in required[self.kind] and getattr(self, field) is not None:
                raise ValueError(f"{self.kind} does not use {field}")
        if self.kind != "preferred_assignment" and self.strength != "hard":
            raise ValueError("This rule type must be hard")
        if (
            self.kind == "resource_unavailable"
            and self.window
            and self.window.start == self.window.end
        ):
            raise ValueError("Unavailability must have a positive duration")
        return self


class DrivingRules(Model):
    """Driver hours policy. Defaults follow a reported TGA-style rule set and
    must be confirmed against the current regulation before live use.

    Non-work time (waiting, rest, pauses) that lasts at least ``break_minutes``
    resets continuous driving; at least ``daily_rest_minutes`` resets the
    driving day. A driving day may not span more than ``max_duty_span_minutes``
    from its first to its last work.
    """

    max_continuous_driving_minutes: int = Field(default=270, ge=30, le=720)
    break_minutes: int = Field(default=45, ge=1, le=240)
    max_daily_driving_minutes: int = Field(default=540, ge=60, le=900)
    daily_rest_minutes: int = Field(default=660, ge=60, le=1440)
    max_duty_span_minutes: int = Field(default=900, ge=60, le=1440)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.break_minutes >= self.daily_rest_minutes:
            raise ValueError("A break must be shorter than a daily rest")
        if self.max_daily_driving_minutes > self.max_duty_span_minutes:
            raise ValueError("Daily driving cannot exceed the duty span")
        return self

    def elapsed(self, drive_minutes: int) -> int:
        """Elapsed minutes for a rested driver to complete ``drive_minutes`` of driving."""
        t = continuous = daily = span = 0
        remaining = drive_minutes
        while remaining > 0:
            available = min(
                self.max_continuous_driving_minutes - continuous,
                self.max_daily_driving_minutes - daily,
                span + self.max_duty_span_minutes - t,
            )
            if available <= 0:
                if (
                    daily >= self.max_daily_driving_minutes
                    or t - span >= self.max_duty_span_minutes
                ):
                    t += self.daily_rest_minutes
                    continuous = daily = 0
                    span = t
                else:
                    t += self.break_minutes
                    continuous = 0
                continue
            chunk = min(available, remaining)
            t, continuous, daily = t + chunk, continuous + chunk, daily + chunk
            remaining -= chunk
        return t


class DriverHours(Model):
    """Where a driver stands on driving hours when the plan starts (e.g. after yesterday)."""

    driving_since_break_minutes: int = Field(default=0, ge=0, le=1440)
    driving_today_minutes: int = Field(default=0, ge=0, le=1440)
    workday_started_at: datetime | None = None
    last_work_ended_at: datetime

    @field_validator("workday_started_at", "last_work_ended_at")
    @classmethod
    def aware_times(cls, value: datetime | None) -> datetime | None:
        return Window.timezone_required(value) if value else None


class AssignmentLock(Model):
    job_id: Identifier
    team_id: Identifier
    pickup_at: datetime | None = None

    @field_validator("pickup_at")
    @classmethod
    def aware_time(cls, value: datetime | None) -> datetime | None:
        return Window.timezone_required(value) if value else None


class Snapshot(Model):
    schema_version: Literal[1] = 1
    tenant_id: Identifier
    scope_id: Identifier
    name: str = Field(min_length=1, max_length=150)
    mode: Literal["demo", "shadow"] = "demo"
    timezone: Literal["Asia/Riyadh"] = "Asia/Riyadh"
    horizon: Window
    sites: tuple[Site, ...] = Field(max_length=100)
    resources: tuple[Resource, ...] = Field(max_length=900)
    teams: tuple[Team, ...] = Field(max_length=300)
    jobs: tuple[Job, ...] = Field(max_length=2000)
    lanes: tuple[Lane, ...] = Field(max_length=10_000)
    rules: tuple[Rule, ...] = Field(default=(), max_length=500)
    locks: tuple[AssignmentLock, ...] = Field(default=(), max_length=200)
    costs: CostProfile = CostProfile()
    return_to_start: bool = True
    # Calendar exceptions (weekly rest, workshop) must be spent at the home depot.
    rest_at_home: bool = False
    driving_rules: DrivingRules | None = None
    # Driving-hours state per team at the plan start; teams not listed start rested.
    driver_hours: dict[str, DriverHours] = {}
    # Value (minor units) of the 1st, 2nd, ... truck ending the plan at a site, from a
    # look-ahead model; the last value repeats. Planning credit only, never cash.
    end_values: dict[str, tuple[int, ...]] = {}
    # Yesterday's plan (job -> team). Moving a job to another team costs the penalty,
    # so a re-plan only changes communicated work when the gain is worth it.
    previous: dict[str, str] = {}
    change_penalty_minor: int = Field(default=0, ge=0, le=10_000_000)
    freshness_minutes: int = Field(default=24 * 60, ge=1)

    @model_validator(mode="after")
    def references(self) -> Self:
        if not self.sites or not self.teams:
            raise ValueError("At least one site and one team are required")
        if not 0 < (self.horizon.end - self.horizon.start).total_seconds() <= 7 * 86400:
            raise ValueError("The planning horizon must be positive and no longer than seven days")
        for name in ("sites", "resources", "teams", "jobs", "rules"):
            rows = getattr(self, name)
            if len({row.id for row in rows}) != len(rows):
                raise ValueError(f"Duplicate IDs in {name}")
        sites = {site.id for site in self.sites}
        resources = {resource.id: resource for resource in self.resources}
        teams = {team.id for team in self.teams}
        jobs = {job.id for job in self.jobs}
        for resource in self.resources:
            if resource.site_id not in sites:
                raise ValueError(f"Unknown resource site: {resource.id}")
        for team in self.teams:
            for resource_id, kind in zip(
                team.resource_ids, ("tractor", "trailer", "driver"), strict=True
            ):
                if resource_id not in resources or resources[resource_id].kind != kind:
                    raise ValueError(f"Invalid {kind} in team {team.id}")
            if len({resources[r].site_id for r in team.resource_ids}) != 1:
                raise ValueError(f"Team {team.id} is not co-located")
        for job in self.jobs:
            if job.pickup_site_id not in sites or job.delivery_site_id not in sites:
                raise ValueError(f"Unknown job site: {job.id}")
        for team in self.teams:
            if team.home_site_id is not None and team.home_site_id not in sites:
                raise ValueError(f"Unknown home site for team {team.id}")
        if set(self.end_values) - sites:
            raise ValueError("End values refer to unknown sites")
        lane_keys = [(lane.from_site_id, lane.to_site_id) for lane in self.lanes]
        if len(set(lane_keys)) != len(lane_keys):
            raise ValueError("Duplicate directed lanes")
        for lane in self.lanes:
            if lane.from_site_id not in sites or lane.to_site_id not in sites:
                raise ValueError("Unknown lane site")
        for rule in self.rules:
            if rule.customer is not None and rule.customer not in {j.customer for j in self.jobs}:
                raise ValueError(f"Unknown customer in rule {rule.id}")
            for field, allowed in (
                ("resource_id", resources),
                ("team_id", teams),
                ("job_id", jobs),
                ("site_id", sites),
            ):
                if getattr(rule, field) is not None and getattr(rule, field) not in allowed:
                    raise ValueError(f"Unknown {field} in rule {rule.id}")
        if len({lock.job_id for lock in self.locks}) != len(self.locks):
            raise ValueError("Duplicate job locks")
        for lock in self.locks:
            if lock.job_id not in jobs or lock.team_id not in teams:
                raise ValueError("Unknown lock reference")
        if set(self.driver_hours) - teams:
            raise ValueError("Driver hours refer to unknown teams")
        if any(team not in teams for team in self.previous.values()):
            raise ValueError("Previous assignments refer to unknown teams")
        return self

    def home_of(self, team: Team) -> str:
        if team.home_site_id is not None:
            return team.home_site_id
        return next(r.site_id for r in self.resources if r.id == team.tractor_id)

    @property
    def fingerprint(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


class Pause(Model):
    """A break or rest taken on the road during a travel activity."""

    kind: Literal["break", "rest"]
    start: datetime
    end: datetime

    @field_validator("start", "end")
    @classmethod
    def aware_time(cls, value: datetime) -> datetime:
        return Window.timezone_required(value)


class Activity(Model):
    team_id: Identifier
    kind: Literal["empty", "loading", "loaded", "unloading", "turnaround", "waiting", "rest"]
    from_site_id: Identifier
    to_site_id: Identifier
    start: datetime
    end: datetime
    job_id: str | None = None
    distance_m: int = Field(default=0, ge=0)
    pauses: tuple[Pause, ...] = ()

    @field_validator("start", "end")
    @classmethod
    def aware_time(cls, value: datetime) -> datetime:
        return Window.timezone_required(value)

    @property
    def paused_seconds(self) -> int:
        return sum(int((p.end - p.start).total_seconds()) for p in self.pauses)


class Assignment(Model):
    job_id: Identifier
    team_id: Identifier
    pickup_at: datetime
    delivery_at: datetime
    released_at: datetime

    @field_validator("pickup_at", "delivery_at", "released_at")
    @classmethod
    def aware_time(cls, value: datetime) -> datetime:
        return Window.timezone_required(value)


class Finding(Model):
    code: str
    message: str
    entity_ids: tuple[str, ...] = ()


class CostBreakdown(Model):
    available: bool
    distance_minor: int | None
    duty_minor: int | None
    total_minor: int | None
    empty_distance_m: int
    loaded_distance_m: int
    duty_minutes: int
    # Revenue of every assigned job; None when any assigned job lacks a price.
    revenue_minor: int | None = None
    currency: Literal["SAR"] = "SAR"
    exclusions: tuple[str, ...] = ()


class Plan(Model):
    snapshot_hash: str
    method: Literal["baseline", "cp_sat", "lns", "manual"]
    outcome: Literal["optimal", "feasible", "unknown", "proven_infeasible", "model_invalid"]
    coverage: Literal["complete", "partial"]
    assignments: tuple[Assignment, ...] = ()
    activities: tuple[Activity, ...] = ()
    unserved_job_ids: tuple[str, ...] = ()
    findings: tuple[Finding, ...] = ()
    # Information for the dispatcher that does not make the plan invalid.
    notes: tuple[Finding, ...] = ()
    costs: CostBreakdown | None = None
    runtime_ms: int = 0
    objective_penalty_minor: int = 0
    diagnostic: bool = False
    solver_version: str | None = None
    objective_bound: float | None = None
    model_stats: dict[str, int | float] = {}

    @property
    def valid(self) -> bool:
        return not self.findings and self.outcome in ("feasible", "optimal")
