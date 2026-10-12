"""Reviewable CSV adapter with stable identities and explicit source conflicts."""

import csv
import hashlib
import io
from datetime import timedelta
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from freight.csv_safety import ENCODING_COLUMN, ENCODING_VERSION, decode_cell, safe_cell
from freight.db import Audit, ImportBatch, MappingProfile, SourceRow
from freight.domain.models import Job, Lane, Resource, Snapshot
from freight.services import remember_request, repeat_request, revise, workspace

Entity = Literal["jobs", "resources", "lanes"]
HEADERS: dict[str, list[str]] = {
    "jobs": [
        "id",
        "reference",
        "customer",
        "pickup_site_id",
        "delivery_site_id",
        "pickup_start",
        "pickup_end",
        "delivery_start",
        "delivery_end",
        "delivery_window_kind",
        "equipment",
        "weight_kg",
        "priority",
        "state",
        "loading_minutes",
        "unloading_minutes",
        "turnaround_minutes",
        "revenue_minor",
    ],
    "resources": [
        "id",
        "name",
        "kind",
        "site_id",
        "available_start",
        "available_end",
        "confirmed_at",
        "equipment",
        "capacity_kg",
    ],
    "lanes": ["from_site_id", "to_site_id", "distance_m", "duration_minutes", "source"],
}


def identity(entity: str, data: dict[str, Any]) -> str:
    return f"{data['from_site_id']}->{data['to_site_id']}" if entity == "lanes" else str(data["id"])


def flatten(entity: str, data: dict[str, Any]) -> dict[str, Any]:
    output = dict(data)
    windows = (
        {"pickup_window": "pickup", "delivery_window": "delivery"}
        if entity == "jobs"
        else {"availability": "available"}
        if entity == "resources"
        else {}
    )
    for name, prefix in windows.items():
        window = output.pop(name)
        output[prefix + "_start"], output[prefix + "_end"] = window["start"], window["end"]
    return {header: output.get(header) for header in HEADERS[entity]}


def template(snapshot: Snapshot, entity: Entity) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=[*HEADERS[entity], ENCODING_COLUMN])
    writer.writeheader()
    for item in getattr(snapshot, entity):
        writer.writerow(
            {k: safe_cell(v) for k, v in flatten(entity, item.model_dump(mode="json")).items()}
            | {ENCODING_COLUMN: ENCODING_VERSION}
        )
    return output.getvalue()


def parse_row(entity: Entity, raw: dict[str, str]) -> dict[str, Any]:
    data: dict[str, Any] = {k: v.strip() for k, v in raw.items() if v is not None and v.strip()}
    if entity == "jobs":
        for prefix in ("pickup", "delivery"):
            data[prefix + "_window"] = {
                "start": data.pop(prefix + "_start", None),
                "end": data.pop(prefix + "_end", None),
            }
        return Job.model_validate(data).model_dump(mode="json")
    if entity == "resources":
        data["availability"] = {
            "start": data.pop("available_start", None),
            "end": data.pop("available_end", None),
        }
        return Resource.model_validate(data).model_dump(mode="json")
    return Lane.model_validate(data).model_dump(mode="json")


def preview(
    db: Session,
    tenant_id: str,
    entity: Entity,
    content: str,
    source_name: str,
    mapping: dict[str, str],
) -> ImportBatch:
    if len(content.encode()) > 2_000_000:
        raise HTTPException(413, "CSV limit is 2 MB")
    reader = csv.DictReader(io.StringIO(content.lstrip("\ufeff")), strict=True)
    try:
        headers = reader.fieldnames
    except csv.Error as exc:
        raise HTTPException(422, f"Invalid CSV header: {exc}") from exc
    if not headers or len(headers) != len(set(headers)) or len(headers) > 60:
        raise HTTPException(422, "CSV requires unique column headers (maximum 60)")
    if any(k not in HEADERS[entity] or v not in headers for k, v in mapping.items()):
        raise HTTPException(422, "Map canonical field names to columns that exist in this file")
    effective_mapping = mapping or {h: h for h in headers if h in HEADERS[entity]}
    current = workspace(db, tenant_id, lock=True)
    recent = (
        db.scalar(
            select(func.count())
            .select_from(ImportBatch)
            .where(
                ImportBatch.tenant_id == tenant_id,
                ImportBatch.created_at > func.now() - timedelta(minutes=10),
            )
        )
        or 0
    )
    if recent >= 20:
        raise HTTPException(429, "Import preview limit reached. Try again later.")
    current_rows = {identity(entity, row): row for row in current.data[entity]}
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        for number, raw in enumerate(reader, 2):
            if number > 501:
                raise HTTPException(422, "CSV limit is 500 rows")
            item: dict[str, Any] = {
                "line": number,
                "raw": raw,
                "data": None,
                "status": "invalid",
                "errors": [],
            }
            try:
                if None in raw or any(v is None for v in raw.values()):
                    raise ValueError("Row width differs from the header")
                mapped = {k: raw[v] for k, v in effective_mapping.items()}
                if raw.get(ENCODING_COLUMN) == ENCODING_VERSION:
                    mapped = {k: decode_cell(v) for k, v in mapped.items()}
                identity_fields = ("from_site_id", "to_site_id") if entity == "lanes" else ("id",)
                if not all(mapped.get(k, "").strip() for k in identity_fields):
                    raise ValueError("Map every stable identity column before reviewing updates")
                key = identity(entity, {k: mapped[k].strip() for k in identity_fields})
                old = current_rows.get(key)
                if old:
                    # An unmapped column is not an instruction to reset a dispatcher
                    # value to the schema default (notably cancelled job state).
                    preserved = {
                        k: "" if v is None else str(v) for k, v in flatten(entity, old).items()
                    }
                    mapped = preserved | mapped
                data = parse_row(entity, mapped)
                external_id = identity(entity, data)
                if external_id in seen:
                    raise ValueError(
                        "Duplicate stable ID in this file; each job must have its own ID"
                    )
                seen.add(external_id)
                existing = current_rows.get(external_id)
                # Preserve calendar exceptions absent from the flat resource adapter.
                if entity == "resources" and existing:
                    data["unavailable"] = existing.get("unavailable", [])
                if entity == "resources":
                    # A reviewed batch can relocate every member of a fixed team.
                    # Enforce co-location atomically for the selected batch at commit,
                    # not against the old locations of each row's teammates here.
                    if data["site_id"] not in {s["id"] for s in current.data["sites"]}:
                        raise ValueError("Unknown resource site")
                    if existing and existing["kind"] != data["kind"]:
                        raise ValueError("A resource's kind cannot change under an existing ID")
                else:
                    candidate = current.data | {
                        entity: [
                            *(r for key, r in current_rows.items() if key != external_id),
                            data,
                        ]
                    }
                    Snapshot.model_validate(candidate)
                source = db.get(SourceRow, (tenant_id, entity, external_id))
                status = (
                    "new" if existing is None else "unchanged" if existing == data else "update"
                )
                if existing and existing != data and (source is None or source.data != existing):
                    status = "conflict"
                item.update(data=data, external_id=external_id, status=status, previous=existing)
            except (ValidationError, ValueError) as exc:
                item["errors"] = [str(exc)]
            rows.append(item)
    except csv.Error as exc:
        raise HTTPException(422, f"Invalid CSV: {exc}") from exc
    if not rows:
        raise HTTPException(422, "The CSV has no data rows")
    batch = ImportBatch(
        tenant_id=tenant_id,
        base_version=current.version,
        entity=entity,
        source_name=source_name,
        checksum=hashlib.sha256(content.encode()).hexdigest(),
        raw_csv=content,
        mapping=effective_mapping,
        rows=rows,
    )
    db.add(batch)
    db.flush()
    return batch


def commit(
    db: Session,
    tenant_id: str,
    batch_id: str,
    expected_version: int,
    lines: list[int],
    overrides: list[int],
    key: str,
) -> dict[str, Any]:
    # Serialize tenant mutations before the idempotency lookup, including retries.
    current = workspace(db, tenant_id, lock=True)
    body = {
        "operation": "import",
        "batch": batch_id,
        "version": expected_version,
        "lines": sorted(lines),
        "overrides": sorted(overrides),
    }
    previous = repeat_request(db, tenant_id, key, body)
    if previous:
        return previous
    batch = db.get(ImportBatch, (tenant_id, batch_id))
    if batch is None:
        raise HTTPException(404, "Import not found")
    if current.version != expected_version or batch.base_version != expected_version:
        raise HTTPException(
            409, "This import was reviewed against an older revision. Preview the file again."
        )
    if not lines or len(lines) != len(set(lines)):
        raise HTTPException(422, "Select one or more unique rows")
    if len(overrides) != len(set(overrides)) or not set(overrides).issubset(lines):
        raise HTTPException(422, "Conflict overrides must be unique selected rows")
    selected = [r for r in batch.rows if r["line"] in lines]
    if len(selected) != len(lines) or any(r["status"] == "invalid" for r in selected):
        raise HTTPException(422, "Selected rows must exist and pass validation")
    if any(r["status"] == "conflict" and r["line"] not in overrides for r in selected):
        raise HTTPException(
            409, "Explicitly approve each source conflict before replacing current values"
        )
    merged = {identity(batch.entity, row): row for row in current.data[batch.entity]}
    changed = 0
    for row in selected:
        external_id, data = row["external_id"], row["data"]
        changed += merged.get(external_id) != data
        merged[external_id] = data
        source = db.get(SourceRow, (tenant_id, batch.entity, external_id))
        if source:
            source.data = data
        else:
            db.add(
                SourceRow(
                    tenant_id=tenant_id, entity=batch.entity, external_id=external_id, data=data
                )
            )
    snapshot = Snapshot.model_validate(current.data | {batch.entity: list(merged.values())})
    version = (
        revise(db, current, snapshot, f"Reviewed {batch.entity} CSV: {batch.source_name}")
        if changed
        else current.version
    )
    profile = db.get(MappingProfile, (tenant_id, batch.source_name))
    if profile:
        profile.entity, profile.mapping = batch.entity, batch.mapping
    else:
        db.add(
            MappingProfile(
                tenant_id=tenant_id,
                name=batch.source_name,
                entity=batch.entity,
                mapping=batch.mapping,
            )
        )
    result = {"version": version, "changed": changed, "accepted": len(selected)}
    db.add(
        Audit(
            tenant_id=tenant_id,
            kind="import_review_committed",
            actor=db.info.get("actor"),
            data={
                "batch_id": batch_id,
                "accepted_lines": sorted(lines),
                "conflict_overrides": sorted(overrides),
                "base_version": expected_version,
                **result,
            },
        )
    )
    remember_request(db, tenant_id, key, body, result)
    return result
