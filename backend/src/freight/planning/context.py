from dataclasses import dataclass
from functools import cached_property

from freight.domain.models import Job, Lane, Resource, Snapshot, Team
from freight.domain.time import minute_down, minute_up


@dataclass(frozen=True)
class Context:
    snapshot: Snapshot

    @cached_property
    def jobs(self) -> dict[str, Job]:
        return {j.id: j for j in self.snapshot.jobs if j.state == "confirmed"}

    @cached_property
    def resources(self) -> dict[str, Resource]:
        return {r.id: r for r in self.snapshot.resources}

    def lane(self, start: str, end: str) -> Lane:
        if start == end:
            return Lane(from_site_id=start, to_site_id=end, distance_m=0, duration_minutes=0)
        return self.lanes[start, end]

    @cached_property
    def lanes(self) -> dict[tuple[str, str], Lane]:
        return {(lane.from_site_id, lane.to_site_id): lane for lane in self.snapshot.lanes}

    def team_start(self, team: Team) -> tuple[str, int]:
        resources = self.resources
        origin = self.snapshot.horizon.start
        return resources[team.tractor_id].site_id, max(
            0, *(minute_up(resources[r].availability.start, origin) for r in team.resource_ids)
        )

    def team_end(self, team: Team) -> tuple[str | None, int]:
        resources = self.resources
        origin = self.snapshot.horizon.start
        end = min(minute_down(resources[r].availability.end, origin) for r in team.resource_ids)
        rules = [
            r
            for r in self.snapshot.rules
            if r.kind == "required_end" and r.team_id == team.id and r.window
        ]
        site = resources[team.tractor_id].site_id if self.snapshot.return_to_start else None
        if rules:
            site = rules[0].site_id
            end = min(end, *(minute_down(r.window.end, origin) for r in rules if r.window))
        return site, end

    def eligible(self, job: Job, team: Team) -> bool:
        trailer = self.resources[team.trailer_id]
        if trailer.equipment != job.equipment or (trailer.capacity_kg or 0) < job.weight_kg:
            return False
        if any(lock.job_id == job.id and lock.team_id != team.id for lock in self.snapshot.locks):
            return False
        for rule in self.snapshot.rules:
            if (
                rule.kind == "customer_eligibility"
                and rule.team_id == team.id
                and rule.customer != job.customer
            ):
                return False
            if (
                rule.kind == "preferred_assignment"
                and rule.strength == "hard"
                and rule.job_id == job.id
                and rule.team_id != team.id
            ):
                return False
        return True

    def blocked(self, team: Team) -> list[tuple[int, int]]:
        origin = self.snapshot.horizon.start
        windows = [w for r in team.resource_ids for w in self.resources[r].unavailable]
        windows.extend(
            r.window
            for r in self.snapshot.rules
            if r.kind == "resource_unavailable" and r.resource_id in team.resource_ids and r.window
        )
        merged: list[tuple[int, int]] = []
        for start, end in sorted(
            (minute_down(w.start, origin), minute_up(w.end, origin))
            for w in windows
            if w.start < w.end
        ):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            else:
                merged.append((start, end))
        return merged
