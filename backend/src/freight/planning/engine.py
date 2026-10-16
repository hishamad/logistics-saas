"""Ruin-and-recreate planner for fixed full-truckload teams.

A route simulator walks each team through its jobs minute by minute. It adds
breaks and daily rest (when the snapshot has driving rules), works around
calendar exceptions, and drives home before an exception that must be spent at
home. A greedy insertion builds the first plan; large-neighbourhood search then
repeatedly removes and reinserts jobs and keeps improvements. Offered jobs are
kept only when their revenue exceeds the extra cost. The independent validator
checks the materialized plan; nothing here is trusted on its own.
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from time import perf_counter
from typing import Literal, cast

from freight.domain.models import Activity, Assignment, Job, Pause, Plan, Snapshot
from freight.domain.time import minute_down, minute_up
from freight.planning.context import Context
from freight.validation.validator import input_findings, validate_plan

UNSERVED_PENALTY = 10_000_000  # search-only cost (minor units) of leaving confirmed work unserved
LOCKED_WEIGHT = 10  # frozen, already communicated work outranks every other job
FOREVER = 10**9


class Infeasible(Exception):
    """The route cannot be executed under the snapshot's rules."""


@dataclass(slots=True)
class State:
    t: int  # minutes since the horizon start
    loc: str
    cont: int = 0  # driving since the last break
    day: int = 0  # driving since the last daily rest
    span: int | None = None  # start of the current working day
    idle: int = FOREVER  # contiguous non-work minutes so far
    started: bool = False  # nothing is recorded before the team's first activity
    dist: int = 0  # metres
    duty: int = 0  # paid minutes
    room: int = FOREVER  # how much later everything so far could have happened
    frozen: bool = False  # an exception was met; the day so far can no longer slide
    span_fixed: bool = False  # the working day began before this plan; its start cannot move

    def copy(self) -> State:
        return State(
            self.t,
            self.loc,
            self.cont,
            self.day,
            self.span,
            self.idle,
            self.started,
            self.dist,
            self.duty,
            self.room,
            self.frozen,
            self.span_fixed,
        )


@dataclass(frozen=True, slots=True)
class TeamInfo:
    id: str
    start: str
    ready: int
    home: str
    end_site: str | None
    end_limit: int
    available_until: int
    blocks: tuple[tuple[int, int, bool], ...]  # (start, end, must be spent at home)
    # Driving-hours state at the start: (since break, today, workday start, last work end).
    hours: tuple[int, int, int | None, int] | None = None


@dataclass
class Recorder:
    team_id: str
    activities: list[tuple[str, str, str, int, int, str | None, int, list[tuple[str, int, int]]]]
    assignments: list[tuple[str, int, int, int]]


class Engine:
    def __init__(self, snapshot: Snapshot, seed: int = 7) -> None:
        self.snapshot = snapshot
        self.rng = random.Random(seed)
        self.context = Context(snapshot)
        origin = self.origin = snapshot.horizon.start
        self.horizon_end = minute_down(snapshot.horizon.end, origin)
        self.lanes = {
            (lane.from_site_id, lane.to_site_id): (lane.duration_minutes, lane.distance_m)
            for lane in snapshot.lanes
        }
        self.lanes.update({(s.id, s.id): (0, 0) for s in snapshot.sites})
        rules = snapshot.driving_rules
        self.rules = rules
        self.max_cont = rules.max_continuous_driving_minutes if rules else FOREVER
        self.max_day = rules.max_daily_driving_minutes if rules else FOREVER
        self.max_span = rules.max_duty_span_minutes if rules else FOREVER
        self.brk = rules.break_minutes if rules else FOREVER
        self.rest = rules.daily_rest_minutes if rules else FOREVER
        costs = snapshot.costs
        self.per_km = float(costs.distance_minor_per_km or 100)
        self.per_minute = float(costs.duty_minor_per_hour or 60) / 60
        self.jobs = {j.id: j for j in snapshot.jobs if j.state in ("confirmed", "offered")}
        self.window: dict[str, tuple[int, int, int, int]] = {}
        for job in self.jobs.values():
            offset = job.unloading_minutes if job.delivery_window_kind == "completion" else 0
            self.window[job.id] = (
                minute_up(job.pickup_window.start, origin),
                min(minute_down(job.pickup_window.end, origin), self.horizon_end - 1),
                minute_up(job.delivery_window.start, origin) - offset,
                minute_down(job.delivery_window.end, origin) - offset,
            )
        self.locks = {
            lock.job_id: (
                lock.team_id,
                minute_up(lock.pickup_at, origin) if lock.pickup_at else None,
            )
            for lock in snapshot.locks
        }
        self.penalties: dict[tuple[str, str], int] = {}
        for rule in snapshot.rules:
            if rule.kind == "preferred_assignment" and rule.strength == "soft":
                for team in snapshot.teams:
                    if team.id != rule.team_id and rule.job_id:
                        key = (rule.job_id, team.id)
                        self.penalties[key] = self.penalties.get(key, 0) + rule.penalty_minor
        if snapshot.change_penalty_minor:
            for job_id, before in snapshot.previous.items():
                if job_id in self.jobs:
                    for team in snapshot.teams:
                        if team.id != before:
                            key = (job_id, team.id)
                            self.penalties[key] = (
                                self.penalties.get(key, 0) + snapshot.change_penalty_minor
                            )
        self.teams = {team.id: self._team_info(team.id) for team in snapshot.teams}
        self.eligible = {
            job.id: [t.id for t in snapshot.teams if self.context.eligible(job, t)]
            for job in self.jobs.values()
        }
        self.elapsed_cache: dict[int, int] = {}
        self.values = snapshot.end_values
        self.max_gain = max((v for curve in self.values.values() for v in curve), default=0)

    # ----- static data -------------------------------------------------------------

    def _team_info(self, team_id: str) -> TeamInfo:
        team = next(t for t in self.snapshot.teams if t.id == team_id)
        resources = self.context.resources
        start, ready = self.context.team_start(team)
        end_site, end_limit = self.context.team_end(team)
        origin = self.origin
        calendar = [
            (minute_down(w.start, origin), minute_up(w.end, origin), self.snapshot.rest_at_home)
            for r in team.resource_ids
            for w in resources[r].unavailable
            if w.start < w.end
        ]
        approved = [
            (minute_down(r.window.start, origin), minute_up(r.window.end, origin), False)
            for r in self.snapshot.rules
            if r.kind == "resource_unavailable" and r.resource_id in team.resource_ids and r.window
        ]
        merged: list[list[int | bool]] = []
        for s, e, home in sorted(calendar + approved):
            if merged and s <= int(merged[-1][1]):
                merged[-1][1] = max(int(merged[-1][1]), e)
                merged[-1][2] = bool(merged[-1][2]) or home
            else:
                merged.append([s, e, home])
        until = min(minute_down(resources[r].availability.end, origin) for r in team.resource_ids)
        known = self.snapshot.driver_hours.get(team.id)
        hours = (
            (
                known.driving_since_break_minutes,
                known.driving_today_minutes,
                minute_down(known.workday_started_at, origin) if known.workday_started_at else None,
                minute_up(known.last_work_ended_at, origin),
            )
            if known and self.rules
            else None
        )
        return TeamInfo(
            hours=hours,
            id=team.id,
            start=start,
            ready=ready,
            home=self.snapshot.home_of(team),
            end_site=end_site,
            end_limit=end_limit,
            available_until=until,
            blocks=tuple((int(s), int(e), bool(h)) for s, e, h in merged),
        )

    def initial(self, info: TeamInfo) -> State:
        """The team's notebook at the plan start, carrying over yesterday's driving hours."""
        if info.hours is None:
            return State(t=info.ready, loc=info.start)
        cont, day, span, last_work = info.hours
        return State(
            t=info.ready,
            loc=info.start,
            cont=cont,
            day=day,
            span=span,
            idle=max(0, info.ready - last_work),
            span_fixed=span is not None,
        )

    def lane(self, a: str, b: str) -> tuple[int, int]:
        return self.lanes[a, b]

    def elapsed(self, drive: int) -> int:
        """Elapsed minutes for a fresh driver to cover ``drive`` minutes of driving."""
        if self.rules is None:
            return drive
        cached = self.elapsed_cache.get(drive)
        if cached is None:
            cached = self.elapsed_cache[drive] = self.rules.elapsed(drive)
        return cached

    # ----- route simulation --------------------------------------------------------

    @staticmethod
    def _block_after(info: TeamInfo, t: int) -> tuple[int, int, bool] | None:
        for block in info.blocks:
            if block[1] > t:
                return block
        return None

    def _resets(self, s: State) -> None:
        if s.idle >= self.brk:
            s.cont = 0
        if s.idle >= self.rest:
            s.day, s.span, s.span_fixed = 0, None, False

    def _idle(self, s: State, minutes: int, kind: str, rec: Recorder | None) -> None:
        if minutes <= 0:
            return
        if not s.started:
            s.t += minutes
            if s.idle < FOREVER:
                s.idle += minutes  # time before the first activity is rest too
            return
        if rec is not None:
            rec.activities.append((kind, s.loc, s.loc, s.t, s.t + minutes, None, 0, []))
        s.t += minutes
        s.idle += minutes
        if kind == "waiting":
            s.duty += minutes

    def _wait_until(
        self, info: TeamInfo, s: State, until: int, rec: Recorder | None, rest: bool = False
    ) -> None:
        while s.t < until:
            block = self._block_after(info, s.t)
            if block and block[0] <= s.t:
                if block[2] and s.loc != info.home:
                    raise Infeasible
                s.frozen = s.frozen or s.started
                self._idle(s, min(block[1], until) - s.t, "rest", rec)
                continue
            end = min(until, block[0] if block else FOREVER)
            length = end - s.t
            kind = "rest" if rest or (self.rules and length >= self.rest) else "waiting"
            if kind == "waiting" and s.started:
                length -= self._slide(s, length, rec)
            self._idle(s, length, kind, rec)

    def _cap_fixed_day(self, s: State) -> None:
        """Work in a workday that began before the plan cannot be moved past its duty span.

        A later slide shifts everything done so far, including this work, but the day's
        start stays where it was, so cap how far it may go.
        """
        if s.span_fixed and s.span is not None:
            s.room = min(s.room, max(0, s.span + self.max_span - s.t))

    def _slide(self, s: State, wait: int, rec: Recorder | None) -> int:
        """Turn paid waiting into unpaid time at the depot by leaving later.

        Shifting everything done so far later keeps every duration (so driving-hours
        state is unchanged) and is allowed while each earlier deadline still holds.
        The part of the wait a driver needs as a legal break or rest is kept.
        """
        if s.frozen or s.room <= 0 or s.span_fixed:
            return 0  # a carried-over working day would only get longer
        shift = min(wait, s.room)
        if self.rules is not None:
            total = s.idle + wait
            if total >= self.rest:
                shift = min(shift, total - self.rest)
            elif total >= self.brk:
                shift = min(shift, total - self.brk)
        if shift <= 0:
            return 0
        s.room -= shift
        s.t += shift  # the day so far now ends later; the remaining wait is shorter
        if s.span is not None:
            s.span += shift
        if rec is not None:
            rec.activities[:] = [
                (
                    k,
                    a,
                    b,
                    start + shift,
                    end + shift,
                    job,
                    dist,
                    [(pk, ps + shift, pe + shift) for pk, ps, pe in pauses],
                )
                for k, a, b, start, end, job, dist, pauses in rec.activities
            ]
            rec.assignments[:] = [
                (job, pickup + shift, delivered + shift, released + shift)
                for job, pickup, delivered, released in rec.assignments
            ]
        return shift

    def _work(
        self,
        info: TeamInfo,
        s: State,
        kind: str,
        minutes: int,
        job_id: str,
        rec: Recorder | None,
        follow: int = 0,
        then_drive: bool = False,
    ) -> int:
        """Start stationary work once no exception or hours limit is in the way."""
        total = minutes + follow + (1 if then_drive else 0)
        for _ in range(12):
            block = self._block_after(info, s.t)
            if block and block[0] < s.t + total:
                if block[2] and s.loc != info.home:
                    raise Infeasible
                self._wait_until(info, s, block[1], rec)
                continue
            if self.rules is not None:
                idle = s.idle
                cont = 0 if idle >= self.brk else s.cont
                rested = idle >= self.rest
                day = 0 if rested else s.day
                span = None if rested else s.span
                if (span is not None and s.t + total - span > self.max_span) or (
                    then_drive and day >= self.max_day
                ):
                    self._wait_until(info, s, s.t + self.rest, rec, rest=True)
                    continue
                if then_drive and cont >= self.max_cont:
                    self._wait_until(info, s, s.t + self.brk, rec)
                    continue
            break
        else:
            raise Infeasible
        self._resets(s)
        start = s.t
        s.idle, s.started = 0, True
        if s.span is None:
            s.span = start
        if rec is not None:
            rec.activities.append((kind, s.loc, s.loc, start, start + minutes, job_id, 0, []))
        s.t += minutes
        s.duty += minutes
        self._cap_fixed_day(s)
        return start

    def _drive(
        self,
        info: TeamInfo,
        s: State,
        dest: str,
        kind: str,
        job_id: str | None,
        rec: Recorder | None,
    ) -> None:
        duration, distance = self.lane(s.loc, dest)
        if duration == 0:
            if kind == "loaded" and rec is not None:
                rec.activities.append((kind, s.loc, dest, s.t, s.t, job_id, 0, []))
            s.loc = dest
            return
        pauses: list[tuple[str, int, int]] = []
        remaining, start, moving = duration, s.t, False
        while remaining > 0:
            block = self._block_after(info, s.t)
            if block and block[0] <= s.t:
                # On the road: a day off at home cannot start here. Not yet moving: wait
                # (at home, if the exception must be spent there) before setting off.
                if (moving and block[2]) or (kind == "loaded" and not moving):
                    raise Infeasible
                s.frozen = True
                if moving:
                    pauses.append(("rest", s.t, block[1]))
                    s.idle += block[1] - s.t
                    s.t = block[1]
                else:
                    self._wait_until(info, s, block[1], rec)
                continue
            self._resets(s)
            avail = min(
                self.max_cont - s.cont,
                self.max_day - s.day,
                (s.span + self.max_span - s.t) if s.span is not None else self.max_span,
            )
            if block:
                avail = min(avail, block[0] - s.t)
            if avail <= 0:
                rest = s.day >= self.max_day or (
                    s.span is not None and s.t - s.span >= self.max_span
                )
                length = self.rest if rest else self.brk
                if not moving:
                    if kind == "loaded":
                        raise Infeasible
                    self._wait_until(info, s, s.t + length, rec, rest=rest)
                else:
                    pauses.append(("rest" if rest else "break", s.t, s.t + length))
                    s.idle += length
                    s.t += length
                continue
            chunk = min(avail, remaining)
            if not moving:
                start, moving, s.started = s.t, True, True
            if s.span is None:
                s.span = s.t
            s.idle = 0
            s.cont += chunk
            s.day += chunk
            s.t += chunk
            s.duty += chunk
            remaining -= chunk
            self._cap_fixed_day(s)
        if rec is not None:
            rec.activities.append((kind, s.loc, dest, start, s.t, job_id, distance, pauses))
        s.loc = dest
        s.dist += distance

    def _home_block(self, info: TeamInfo, t: int) -> tuple[int, int, bool] | None:
        return next((b for b in info.blocks if b[2] and b[1] > t), None)

    def _go_home_for(
        self, info: TeamInfo, s: State, block: tuple[int, int, bool], rec: Recorder | None
    ) -> None:
        if s.loc != info.home:
            self._drive(info, s, info.home, "empty", None, rec)
        if s.t > block[0]:
            raise Infeasible
        self._wait_until(info, s, block[1], rec)

    def _job(self, info: TeamInfo, s: State, job: Job, rec: Recorder | None) -> None:
        for _ in range(8):
            block = self._home_block(info, s.t)
            if block is None:
                break
            if block[0] <= s.t:
                # Already in a day off: wait it out (this fails unless the team is home).
                self._wait_until(info, s, block[1], rec)
                continue
            pickup_open, _, _, delivery_close = self.window[job.id]
            home_drive = self.lane(job.delivery_site_id, info.home)[0]
            bound = (
                max(s.t, delivery_close)
                + job.unloading_minutes
                + job.turnaround_minutes
                + self.elapsed(home_drive)
                + (self.rest if self.rules else 0)
            )
            if block[0] >= bound:
                break
            trial = s.copy()
            try:
                self._job_core(info, trial, job, None)
                after = trial.copy()
                if after.loc != info.home:
                    self._drive(info, after, info.home, "empty", None, None)
                if after.t > block[0]:
                    raise Infeasible
            except Infeasible:
                self._go_home_for(info, s, block, rec)
                continue
            if rec is None:
                for name in State.__slots__:
                    setattr(s, name, getattr(trial, name))
                return
            break
        self._job_core(info, s, job, rec)

    def _job_core(self, info: TeamInfo, s: State, job: Job, rec: Recorder | None) -> None:
        pickup_open, pickup_close, delivery_open, delivery_close = self.window[job.id]
        locked = self.locks.get(job.id)
        if locked and locked[1] is not None:
            pickup_open = pickup_close = locked[1]
        if s.loc != job.pickup_site_id:
            if not s.started:
                drive = self.elapsed(self.lane(s.loc, job.pickup_site_id)[0])
                depart = max(s.t, pickup_open - drive)
                if not any(b[0] < pickup_open and b[1] > s.t for b in info.blocks):
                    if s.idle < FOREVER:
                        s.idle += depart - s.t
                    s.t = depart
            self._drive(info, s, job.pickup_site_id, "empty", None, rec)
        if s.t > pickup_close:
            raise Infeasible
        self._wait_until(info, s, pickup_open, rec)
        loading = self._work(info, s, "loading", job.loading_minutes, job.id, rec, then_drive=True)
        if loading > pickup_close or (locked and locked[1] is not None and loading != locked[1]):
            raise Infeasible
        s.room = min(s.room, 0 if locked and locked[1] is not None else pickup_close - loading)
        self._drive(info, s, job.delivery_site_id, "loaded", job.id, rec)
        if s.t > delivery_close:
            raise Infeasible
        self._wait_until(info, s, delivery_open, rec)
        unloading = self._work(
            info, s, "unloading", job.unloading_minutes, job.id, rec, follow=job.turnaround_minutes
        )
        if unloading > delivery_close:
            raise Infeasible
        s.room = min(s.room, delivery_close - unloading)
        if rec is not None:
            rec.activities.append(
                ("turnaround", s.loc, s.loc, s.t, s.t + job.turnaround_minutes, job.id, 0, [])
            )
        s.t += job.turnaround_minutes
        s.duty += job.turnaround_minutes
        if s.t > info.available_until:
            raise Infeasible
        if rec is not None:
            # Read times back from the recorded activities: a later slide may have moved them.
            starts = {
                k: (start, end) for k, _, _, start, end, j, _, _ in rec.activities if j == job.id
            }
            loaded_at, (unload_start, unload_end) = starts["loading"][0], starts["unloading"]
            delivered = unload_start if job.delivery_window_kind == "service_start" else unload_end
            rec.assignments.append((job.id, loaded_at, delivered, s.t))

    def _finish(self, info: TeamInfo, s: State, rec: Recorder | None) -> None:
        if info.end_site is not None:
            if s.loc != info.end_site:
                self._drive(info, s, info.end_site, "empty", None, rec)
            if s.t > info.end_limit:
                raise Infeasible
        block = self._home_block(info, s.t)
        if block and s.loc != info.home:
            if info.end_site is not None:
                raise Infeasible
            self._drive(info, s, info.home, "empty", None, rec)
            if s.t > block[0]:
                raise Infeasible
        if s.t > info.available_until:
            raise Infeasible

    def cost(self, s: State) -> float:
        return s.dist / 1000 * self.per_km + s.duty * self.per_minute

    def gain(self, site: str, n: int) -> int:
        """Look-ahead value of the n-th truck ending at a site (n >= 1)."""
        curve = self.values.get(site)
        if not curve or n < 1:
            return 0
        return curve[min(n, len(curve)) - 1]

    def worth(self, site: str, n: int) -> int:
        return sum(self.gain(site, k) for k in range(1, n + 1))

    def run(
        self, info: TeamInfo, state: State, jobs: list[str], rec: Recorder | None = None
    ) -> tuple[float, str] | None:
        """Cost of finishing the route from ``state``, and where the team ends."""
        s = state.copy()
        try:
            for job_id in jobs:
                self._job(info, s, self.jobs[job_id], rec)
            self._finish(info, s, rec)
        except Infeasible:
            return None
        return self.cost(s), s.loc

    def prefixes(self, info: TeamInfo, route: list[str]) -> tuple[list[State], float, str] | None:
        s = self.initial(info)
        states = [s.copy()]
        try:
            for job_id in route:
                self._job(info, s, self.jobs[job_id], None)
                states.append(s.copy())
            end = s.copy()
            self._finish(info, end, None)
        except Infeasible:
            return None
        return states, self.cost(end), end.loc


@dataclass
class Solution:
    routes: dict[str, list[str]]
    states: dict[str, list[State]]
    costs: dict[str, float]
    where: dict[str, str]  # job -> team
    ends: dict[str, str]  # team -> where it ends


class Search:
    def __init__(self, engine: Engine) -> None:
        self.e = engine
        self.confirmed = [j for j, job in engine.jobs.items() if job.state == "confirmed"]
        self.offered = [j for j, job in engine.jobs.items() if job.state == "offered"]
        self.solution = Solution({}, {}, {}, {}, {})
        self.free = [t for t, info in engine.teams.items() if info.end_site is None]
        for team_id, info in engine.teams.items():
            computed = engine.prefixes(info, [])
            states, cost, end = computed if computed else ([engine.initial(info)], 0.0, info.start)
            self.solution.routes[team_id] = []
            self.solution.states[team_id] = states
            self.solution.costs[team_id] = cost
            self.solution.ends[team_id] = end

    def objective(self, sol: Solution | None = None) -> float:
        sol = sol or self.solution
        e = self.e
        total = sum(sol.costs.values())
        total += sum(e.penalties.get((j, t), 0) for j, t in sol.where.items())
        total += UNSERVED_PENALTY * sum(
            LOCKED_WEIGHT if j in e.locks else 1 for j in self.confirmed if j not in sol.where
        )
        total -= sum(
            e.jobs[j].revenue_minor or 0 for j in sol.where if e.jobs[j].state == "offered"
        )
        return total - self.end_worth(sol)

    def end_worth(self, sol: Solution | None = None) -> int:
        """Look-ahead credit for where free-ending teams finish, with diminishing returns."""
        if not self.e.values:
            return 0
        sol = sol or self.solution
        counts = Counter(sol.ends[t] for t in self.free)
        return sum(self.e.worth(site, n) for site, n in counts.items())

    def _shift(self, team_id: str, end: str, counts: Counter[str]) -> float:
        """Change in look-ahead credit (as cost) if this team ends at ``end`` instead."""
        e = self.e
        old = self.solution.ends[team_id]
        if not e.values or old == end or e.teams[team_id].end_site is not None:
            return 0.0
        return e.gain(old, counts[old]) - e.gain(end, counts[end] + 1)

    def _bound(self, team_id: str, position: int, job: Job) -> float:
        """Cheap, approximate lower bound on the extra cost of an insertion."""
        e = self.e
        route = self.solution.routes[team_id]
        here = self.solution.states[team_id][position].loc
        if position < len(route):
            after: str | None = e.jobs[route[position]].pickup_site_id
        else:
            after = e.teams[team_id].end_site
        to_pickup = e.lane(here, job.pickup_site_id)
        loaded = e.lane(job.pickup_site_id, job.delivery_site_id)
        onward = e.lane(job.delivery_site_id, after) if after else (0, 0)
        skipped = e.lane(here, after) if after else (0, 0)
        metres = to_pickup[1] + loaded[1] + onward[1] - skipped[1]
        minutes = (
            to_pickup[0]
            + loaded[0]
            + onward[0]
            - skipped[0]
            + job.loading_minutes
            + job.unloading_minutes
            + job.turnaround_minutes
        )
        return metres / 1000 * e.per_km + max(0, minutes) * e.per_minute

    def best_insertion(
        self, job_id: str, noise: float = 0.0, blink: float = 0.0
    ) -> tuple[float, str, int] | None:
        e, sol = self.e, self.solution
        job = e.jobs[job_id]
        pickup_open, pickup_close, _, _ = e.window[job_id]
        locked = e.locks.get(job_id)
        options: list[tuple[float, str, int]] = []
        for team_id in e.eligible[job_id]:
            if locked and locked[0] != team_id:
                continue
            states = sol.states[team_id]
            route = sol.routes[team_id]
            for position in range(len(route) + 1):
                state = states[position]
                if state.t + e.lane(state.loc, job.pickup_site_id)[0] > pickup_close:
                    break
                if position < len(route):
                    following = e.jobs[route[position]]
                    earliest_release = (
                        max(
                            max(state.t, pickup_open)
                            + job.loading_minutes
                            + e.lane(job.pickup_site_id, job.delivery_site_id)[0],
                            e.window[job_id][2],
                        )
                        + job.unloading_minutes
                        + job.turnaround_minutes
                    )
                    reach = (
                        earliest_release + e.lane(job.delivery_site_id, following.pickup_site_id)[0]
                    )
                    if reach > e.window[following.id][1]:
                        continue
                bound = self._bound(team_id, position, job) + e.penalties.get((job_id, team_id), 0)
                if position == len(route):
                    bound -= e.max_gain  # a new last job may move the truck somewhere valuable
                options.append((bound, team_id, position))
        options.sort()
        counts = Counter(sol.ends[t] for t in self.free) if e.values else Counter()
        best: tuple[float, str, int] | None = None
        for bound, team_id, position in options:
            if best is not None and bound >= best[0] * (1 + noise) + 1:
                break
            if blink and e.rng.random() < blink:
                continue  # SISR "blink": occasionally skip a position to diversify
            info = e.teams[team_id]
            route = sol.routes[team_id]
            result = e.run(info, sol.states[team_id][position], [job_id, *route[position:]])
            if result is None:
                continue
            cost, end = result
            delta = (
                cost
                - sol.costs[team_id]
                + e.penalties.get((job_id, team_id), 0)
                + self._shift(team_id, end, counts)
            )
            if noise:
                delta += abs(delta) * noise * (2 * e.rng.random() - 1)
            if best is None or delta < best[0]:
                best = (delta, team_id, position)
        return best

    def insert(self, job_id: str, team_id: str, position: int) -> None:
        sol = self.solution
        sol.routes[team_id].insert(position, job_id)
        sol.where[job_id] = team_id
        self._refresh(team_id)

    def remove(self, job_ids: list[str]) -> None:
        sol = self.solution
        touched = set()
        for job_id in job_ids:
            team_id = sol.where.pop(job_id, None)
            if team_id is not None:
                sol.routes[team_id].remove(job_id)
                touched.add(team_id)
        for team_id in touched:
            self._refresh(team_id)

    def _refresh(self, team_id: str) -> None:
        sol = self.solution
        computed = self.e.prefixes(self.e.teams[team_id], sol.routes[team_id])
        if computed is None:
            # Removing work can, rarely, break a home-rest schedule; repair by dropping jobs.
            route = sol.routes[team_id]
            while route and computed is None:
                sol.where.pop(route.pop(), None)
                computed = self.e.prefixes(self.e.teams[team_id], route)
        if computed is None:
            # Even an idle day breaks the rules (e.g. a tired driver cannot reach home before
            # a day off). Keep the team idle; the validator reports the problem plainly.
            info = self.e.teams[team_id]
            computed = ([self.e.initial(info)], 0.0, info.start)
        sol.states[team_id], sol.costs[team_id], sol.ends[team_id] = computed

    def recreate(
        self,
        candidates: list[str],
        noise: float = 0.0,
        ejections: int = 10**6,
        order: str = "tight",
        blink: float = 0.0,
    ) -> None:
        e = self.e
        confirmed = [j for j in candidates if e.jobs[j].state == "confirmed"]
        offered = [j for j in candidates if e.jobs[j].state == "offered"]
        if order == "random":
            e.rng.shuffle(confirmed)
        elif order == "long":
            confirmed.sort(
                key=lambda j: -e.lanes[e.jobs[j].pickup_site_id, e.jobs[j].delivery_site_id][0]
            )
        else:
            confirmed.sort(key=lambda j: (j not in e.locks, e.window[j][1]))
        offered.sort(key=lambda j: -(e.jobs[j].revenue_minor or 0))
        confirmed.sort(key=lambda j: j not in e.locks)  # stable: frozen work always first
        for job_id in confirmed:
            found = self.best_insertion(job_id, noise, blink)
            if found:
                self.insert(job_id, found[1], found[2])
            elif job_id in e.locks:
                self.make_room_for_locked(job_id, noise)
            elif ejections > 0:
                ejections -= 1
                self.eject_offer_for(job_id)
        for job_id in offered:
            found = self.best_insertion(job_id, noise)
            if found and found[0] < (e.jobs[job_id].revenue_minor or 0):
                self.insert(job_id, found[1], found[2])

    def make_room_for_locked(self, job_id: str, noise: float) -> None:
        """Move unfrozen work off a frozen job's truck, place the job, re-place the rest."""
        e, sol = self.e, self.solution
        team_id = e.locks[job_id][0]
        movable = [j for j in sol.routes[team_id] if j not in e.locks]
        self.remove(movable)
        found = self.best_insertion(job_id)
        if found:
            self.insert(job_id, found[1], found[2])
        self.recreate(movable, noise, ejections=0)

    def eject_offer_for(self, job_id: str) -> bool:
        """Confirmed work outranks optional loads: drop one offer to make room."""
        e, sol = self.e, self.solution
        job = e.jobs[job_id]
        pickup_close = e.window[job_id][1]
        best: tuple[float, str, str, int] | None = None
        holders = [
            t
            for t in e.eligible[job_id]
            if any(e.jobs[j].state == "offered" for j in sol.routes[t])
        ]
        holders.sort(
            key=lambda t: min(
                self._bound(t, position, job) for position in range(len(sol.routes[t]) + 1)
            )
        )
        for team_id in holders[:6]:
            info = e.teams[team_id]
            for offer in [j for j in sol.routes[team_id] if e.jobs[j].state == "offered"]:
                route = [j for j in sol.routes[team_id] if j != offer]
                computed = e.prefixes(info, route)
                if computed is None:
                    continue
                states = computed[0]
                for position in range(len(route) + 1):
                    state = states[position]
                    if state.t + e.lane(state.loc, job.pickup_site_id)[0] > pickup_close:
                        break
                    result = e.run(info, state, [job_id, *route[position:]])
                    if result is None:
                        continue
                    loss = (
                        result[0]
                        - sol.costs[team_id]
                        + (e.jobs[offer].revenue_minor or 0)
                        + e.penalties.get((job_id, team_id), 0)
                    )
                    if best is None or loss < best[0]:
                        best = (loss, team_id, offer, position)
        if best is None:
            return False
        _, team_id, offer, position = best
        self.remove([offer])
        self.insert(job_id, team_id, position)
        return True

    RUINS = ("related", "string", "routes", "random")

    def ruin(self, operator: str) -> list[str]:
        e, sol = self.e, self.solution
        assigned = list(sol.where)
        if not assigned:
            return []
        size = e.rng.randint(2, max(3, min(30, len(assigned) // 6)))
        seed = e.jobs[e.rng.choice(assigned)]
        open_minute = e.window[seed.id][0]

        def related(j: str) -> float:
            other = e.jobs[j]
            metres = e.lanes[seed.pickup_site_id, other.pickup_site_id][1]
            metres += e.lanes[seed.delivery_site_id, other.delivery_site_id][1]
            return metres / 1000 + abs(e.window[j][0] - open_minute) / 6

        if operator == "related":
            return sorted(assigned, key=related)[:size]
        if operator == "string":
            # SISR: cut short strings of consecutive jobs out of routes near the seed.
            closest: dict[str, tuple[float, int]] = {}
            for team_id, route in sol.routes.items():
                for index, j in enumerate(route):
                    score = related(j)
                    if team_id not in closest or score < closest[team_id][0]:
                        closest[team_id] = (score, index)
            nearest = sorted(closest.items(), key=lambda item: item[1][0])
            removed: list[str] = []
            for team_id, (_, index) in nearest[: e.rng.randint(1, 4)]:
                route = sol.routes[team_id]
                length = e.rng.randint(1, min(len(route), 4))
                first = e.rng.randint(max(0, index - length + 1), min(index, len(route) - length))
                removed += route[first : first + length]
            return removed
        if operator == "routes":
            busy = [t for t, r in sol.routes.items() if r]
            chosen = e.rng.sample(busy, min(len(busy), e.rng.randint(1, 3)))
            return [j for t in chosen for j in sol.routes[t]][: size * 2]
        return e.rng.sample(assigned, min(size, len(assigned)))

    def copy_solution(self) -> Solution:
        sol = self.solution
        return Solution(
            {t: list(r) for t, r in sol.routes.items()},
            dict(sol.states),
            dict(sol.costs),
            dict(sol.where),
            dict(sol.ends),
        )

    def improve(
        self, deadline: float, offers: bool = True, rounds: int | None = None
    ) -> dict[str, int]:
        """Ruin and recreate with adaptive operator choice and record-to-record acceptance.

        A candidate is accepted when it is within a shrinking threshold of the best
        plan found (Santini, Ropke and Hvattum 2018 found this rule consistently strong).
        """
        e = self.e
        current = self.objective()
        best, best_value = self.copy_solution(), current
        started = perf_counter()
        budget = max(1e-6, deadline - started)

        def progress() -> float:
            """Share of the budget used: rounds when counting rounds, else time."""
            if rounds is not None:
                return stats["iterations"] / max(1, rounds)
            return (perf_counter() - started) / budget

        threshold0 = 0.005 * abs(current - UNSERVED_PENALTY * self.unserved()) + 1
        weights = dict.fromkeys(self.RUINS, 1.0)
        scores = dict.fromkeys(self.RUINS, 0.0)
        uses = dict.fromkeys(self.RUINS, 0)
        stats = {"iterations": 0, "accepted": 0, "improved": 0}
        while perf_counter() < deadline and (rounds is None or stats["iterations"] < rounds):
            stats["iterations"] += 1
            operator = e.rng.choices(self.RUINS, weights=[weights[o] for o in self.RUINS])[0]
            uses[operator] += 1
            saved = self.copy_solution()
            removed = self.ruin(operator)
            self.remove(removed)
            unserved = [j for j in self.confirmed if j not in self.solution.where]
            retry = e.rng.sample(unserved, min(len(unserved), 5))
            spare = [j for j in self.offered if j not in self.solution.where]
            sample = e.rng.sample(spare, min(len(spare), len(removed) + 2)) if offers else []
            self.recreate(
                list(dict.fromkeys([*removed, *retry, *sample])),
                noise=0.1 if e.rng.random() < 0.2 else 0.0,
                ejections=2,
                order=e.rng.choice(("tight", "tight", "random", "long")),
                blink=0.01,
            )
            value = self.objective()
            threshold = threshold0 * max(0.0, 1 - progress())
            if value < best_value - 1e-6:
                best, best_value = self.copy_solution(), value
                current = value
                stats["improved"] += 1
                stats["accepted"] += 1
                scores[operator] += 3
            elif value < best_value + threshold:
                scores[operator] += 2 if value < current else 1
                current = value
                stats["accepted"] += 1
            else:
                self.solution = saved
            if stats["iterations"] % 50 == 0:
                for o in self.RUINS:
                    if uses[o]:
                        weights[o] = max(0.1, 0.8 * weights[o] + 0.2 * scores[o] / uses[o])
                    scores[o], uses[o] = 0.0, 0
        self.solution = best
        return stats

    def load(self, routes: dict[str, list[str]]) -> None:
        """Start from given routes (e.g. an earlier plan). Jobs that are unknown, or that
        rules, locks or equipment no longer allow on that team, are left for re-insertion."""
        for team_id, route in routes.items():
            if team_id in self.solution.routes:
                self.solution.routes[team_id] = [
                    j for j in route if j in self.e.jobs and team_id in self.e.eligible[j]
                ]
                for job_id in self.solution.routes[team_id]:
                    self.solution.where[job_id] = team_id
                self._refresh(team_id)

    def insertion_on(self, job_id: str, team_id: str) -> tuple[float, int] | None:
        """Cheapest extra cost (and position) of adding a job to one team's route."""
        e, sol = self.e, self.solution
        info, route = e.teams[team_id], sol.routes[team_id]
        best: tuple[float, int] | None = None
        for position in range(len(route) + 1):
            result = e.run(info, sol.states[team_id][position], [job_id, *route[position:]])
            if result is not None:
                delta = result[0] - sol.costs[team_id] + e.penalties.get((job_id, team_id), 0)
                if best is None or delta < best[0]:
                    best = (delta, position)
        return best

    def unserved(self) -> int:
        return sum(1 for j in self.confirmed if j not in self.solution.where)


def routes_of(plan: Plan) -> dict[str, list[str]]:
    """Each team's jobs in pickup order, to continue searching from an earlier plan."""
    routes: dict[str, list[str]] = {}
    for a in sorted(plan.assignments, key=lambda a: a.pickup_at):
        routes.setdefault(a.team_id, []).append(a.job_id)
    return routes


def plan_lns(
    snapshot: Snapshot,
    *,
    seconds: float = 30,
    seed: int = 7,
    initial: dict[str, list[str]] | None = None,
    rounds: int | None = None,
) -> Plan:
    """Plan with ruin-and-recreate; ``initial`` continues from an earlier plan's routes.

    By default the search stops after ``seconds``, so results vary slightly with machine
    load. Give ``rounds`` to stop after a fixed number of search rounds instead: the
    same seed then always gives the same plan (``seconds`` remains a safety limit).
    """
    started = perf_counter()
    if rounds is not None:
        seconds = max(seconds, 3600.0)
    problems = input_findings(snapshot)
    confirmed = tuple(j.id for j in snapshot.jobs if j.state == "confirmed")
    if problems:
        return Plan(
            snapshot_hash=snapshot.fingerprint,
            method="lns",
            outcome="model_invalid",
            coverage="partial",
            unserved_job_ids=confirmed,
            findings=problems,
        )
    engine = Engine(snapshot, seed)
    search = Search(engine)
    if initial:
        search.load(initial)
        search.recreate([j for j in search.confirmed if j not in search.solution.where])
    else:
        order = sorted(search.confirmed, key=lambda j: (j not in engine.locks, engine.window[j][0]))
        search.recreate(order)
    construction_ms = round((perf_counter() - started) * 1000)
    construction_value = search.objective()
    if initial:
        # The earlier plan already separated confirmed work from offers.
        stats = search.improve(started + seconds, rounds=rounds)
    else:
        # Phase 1 plans confirmed work alone, so optional loads can never take its place.
        # Phase 2 fills the remaining capacity with offers that earn more than they cost.
        phase_one = started + seconds * (0.6 if search.offered else 1.0)
        first = None if rounds is None else round(rounds * (0.6 if search.offered else 1.0))
        stats = search.improve(phase_one if rounds is None else started + seconds, False, first)
        if search.offered:
            search.recreate(search.offered)
            second = search.improve(
                started + seconds, rounds=None if rounds is None else rounds - (first or 0)
            )
            stats = {k: stats[k] + second[k] for k in stats}
    plan = materialize(engine, search.solution)
    plan = plan.model_copy(
        update={
            "runtime_ms": round((perf_counter() - started) * 1000),
            "model_stats": {
                "construction_ms": construction_ms,
                "construction_objective": round(construction_value),
                "final_objective": round(search.objective()),
                "end_value": search.end_worth(),
                **stats,
            },
        }
    )
    return validate_plan(snapshot, plan)


def materialize(engine: Engine, solution: Solution) -> Plan:
    origin = engine.origin

    def at(minute: int) -> datetime:
        return origin + timedelta(minutes=minute)

    activities: list[Activity] = []
    assignments: list[Assignment] = []
    for team_id, route in solution.routes.items():
        info = engine.teams[team_id]
        recorder = Recorder(team_id, [], [])
        if engine.run(info, engine.initial(info), route, recorder) is None:
            if route:
                raise RuntimeError(f"Route for {team_id} no longer simulates")
            # Even an idle team cannot meet its rules (e.g. it is too far from home for its
            # next day off). Record no work; the validator reports the problem plainly.
            recorder = Recorder(team_id, [], [])
        for kind, a, b, start, end, job_id, distance, pauses in recorder.activities:
            activities.append(
                Activity(
                    team_id=team_id,
                    kind=cast(
                        Literal[
                            "empty",
                            "loading",
                            "loaded",
                            "unloading",
                            "turnaround",
                            "waiting",
                            "rest",
                        ],
                        kind,
                    ),
                    from_site_id=a,
                    to_site_id=b,
                    start=at(start),
                    end=at(end),
                    job_id=job_id,
                    distance_m=distance,
                    pauses=tuple(
                        Pause(kind=cast(Literal["break", "rest"], k), start=at(s), end=at(e))
                        for k, s, e in pauses
                    ),
                )
            )
        for job_id, pickup, delivery, released in recorder.assignments:
            assignments.append(
                Assignment(
                    job_id=job_id,
                    team_id=team_id,
                    pickup_at=at(pickup),
                    delivery_at=at(delivery),
                    released_at=at(released),
                )
            )
    snapshot = engine.snapshot
    served = {a.job_id for a in assignments}
    unserved = tuple(j.id for j in snapshot.jobs if j.state == "confirmed" and j.id not in served)
    return Plan(
        snapshot_hash=snapshot.fingerprint,
        method="lns",
        outcome="feasible",
        coverage="partial" if unserved else "complete",
        assignments=tuple(assignments),
        activities=tuple(activities),
        unserved_job_ids=unserved,
        diagnostic=bool(unserved),
    )
