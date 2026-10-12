from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, computed_field

from freight.domain.models import Finding, Plan, Snapshot


class WorkspaceView(BaseModel):
    role: str = "dispatcher"
    version: int
    snapshot: Snapshot
    name: str
    input_findings: list[Finding]
    ai_configured: bool
    ai_model: str | None


class PlanView(Plan):
    model_config = ConfigDict(extra="ignore", frozen=True)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def valid(self) -> bool:
        return super().valid


class ComparisonView(BaseModel):
    comparable: bool
    reasons: list[str]
    modeled_saving_minor: int | None
    changed_assignments: int
    label: str


class RunResult(BaseModel):
    baseline: PlanView
    candidate: PlanView
    comparison: ComparisonView
    snapshot_hash: str


class RunView(BaseModel):
    id: str
    revision: int
    state: str
    attempt: int
    diagnostic: bool
    seconds: int
    created_at: datetime
    finished_at: datetime | None
    error: str | None
    result: RunResult | None
    snapshot: Snapshot | None = None


class ImportView(BaseModel):
    id: str
    base_version: int
    entity: str
    checksum: str
    mapping: dict[str, str]
    rows: list[dict[str, Any]]
