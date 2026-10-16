"""Answer a dispatcher's "why?" and "what if?" with computed facts, then words.

The engine computes every number: what a job costs on its truck and on the
alternatives, or what changes when the engine actually re-plans under a
hypothetical. Only then may a language model turn those facts into a short
explanation, told to use nothing else (the OptiGuide pattern). Without an API
key, or if the provider fails, a built-in template writes the explanation.
"""

import json
from collections import Counter
from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from openai import OpenAI, OpenAIError, omit

from freight.domain.models import AssignmentLock, Plan, Rule, Snapshot, Window
from freight.planning.diff import diff_plans
from freight.planning.engine import Engine, Search, materialize, plan_lns, routes_of
from freight.settings import get_settings
from freight.validation.validator import validate_plan

RIYADH = ZoneInfo("Asia/Riyadh")
Language = Literal["en", "ar"]


def _sar(minor: float) -> int:
    return round(minor / 100)


def _when(value: datetime) -> str:
    return value.astimezone(RIYADH).strftime("%a %d %b %H:%M")


def _numeric(value: datetime) -> str:
    return value.astimezone(RIYADH).strftime("%Y-%m-%d %H:%M")


def _job_facts(snapshot: Snapshot, job_id: str) -> dict[str, Any]:
    job = next(j for j in snapshot.jobs if j.id == job_id)
    sites = {s.id: s for s in snapshot.sites}
    return {
        "reference": job.reference,
        "customer": job.customer,
        "from": sites[job.pickup_site_id].name,
        "from_ar": sites[job.pickup_site_id].name_ar,
        "to": sites[job.delivery_site_id].name,
        "to_ar": sites[job.delivery_site_id].name_ar,
        "pickup_window_riyadh": f"{_when(job.pickup_window.start)} - {_when(job.pickup_window.end)}",
        "equipment": job.equipment,
        "tonnes": job.weight_kg / 1000,
        "price_sar": _sar(job.revenue_minor) if job.revenue_minor is not None else None,
        "kind": "spot/return offer" if job.state == "offered" else "contract",
    }


def why(snapshot: Snapshot, plan: Plan, job_id: str) -> dict[str, Any]:
    """Why is a job on its truck (or nowhere)? Cost on the chosen truck vs the alternatives."""
    engine = Engine(snapshot)
    search = Search(engine)
    search.load(routes_of(plan))
    names = {t.id: t.name for t in snapshot.teams}
    chosen = search.solution.where.get(job_id)
    facts: dict[str, Any] = {"question": "why", "job": _job_facts(snapshot, job_id)}
    if chosen is not None:
        with_job = search.solution.costs[chosen]
        search.remove([job_id])
        facts["assigned"] = {
            "truck": names[chosen],
            "extra_cost_sar": _sar(with_job - search.solution.costs[chosen]),
        }
        activities = sorted(
            (a for a in plan.activities if a.team_id == chosen), key=lambda a: a.start
        )
        loading = next(
            i for i, a in enumerate(activities) if a.job_id == job_id and a.kind == "loading"
        )
        before = [a for a in activities[:loading] if a.kind == "empty"]
        if before and before[-1].to_site_id == next(
            j.pickup_site_id for j in snapshot.jobs if j.id == job_id
        ):
            facts["assigned"]["empty_km_to_pickup"] = round(before[-1].distance_m / 1000)
        facts["assigned"]["pickup_riyadh"] = _when(activities[loading].start)
    job = next(j for j in snapshot.jobs if j.id == job_id)
    trailers = {r.id: r for r in snapshot.resources if r.kind == "trailer"}
    reasons: Counter[str] = Counter()
    free = Search(engine)  # every truck with nothing else to do
    options = []
    for team in snapshot.teams:
        if team.id == chosen:
            continue
        trailer = trailers[team.trailer_id]
        if trailer.equipment != job.equipment:
            reasons["wrong equipment"] += 1
        elif (trailer.capacity_kg or 0) < job.weight_kg:
            reasons["too heavy for the trailer"] += 1
        elif team.id not in engine.eligible.get(job_id, []):
            reasons["a dispatcher rule or lock"] += 1
        else:
            found = search.insertion_on(job_id, team.id)
            if found is not None:
                options.append((found[0], team.id))
            elif free.insertion_on(job_id, team.id) is not None:
                # Possible for this truck on an empty day: its other work is in the way.
                reasons["busy with other work"] += 1
            else:
                reasons["cannot fit in time (windows, driving hours or days off)"] += 1
    options.sort()
    chosen_cost = facts.get("assigned", {}).get("extra_cost_sar")
    facts["alternatives"] = [
        {
            "truck": names[t],
            "extra_cost_sar": _sar(cost),
            **(
                {"more_than_chosen_sar": _sar(cost) - chosen_cost}
                if chosen_cost is not None
                else {}
            ),
        }
        for cost, t in options[:3]
    ]
    facts["other_trucks_that_could_take_it"] = len(options)
    facts["trucks_that_cannot_take_it"] = dict(reasons)
    return facts


class WhatIfRefused(ValueError):
    """The engine refused the changed situation; the message gives its reasons."""


class WhatIfImpossible(ValueError):
    """The change cannot be carried out at all; explained in English and Arabic."""

    def __init__(self, english: str, arabic: str) -> None:
        super().__init__(english)
        self.english, self.arabic = english, arabic


def changed_situation(snapshot: Snapshot, change: dict[str, Any]) -> tuple[Snapshot, str, str]:
    """The snapshot with a hypothetical change applied, and its description (en, ar).

    change: {"kind": "drop", "job": id}
            {"kind": "unavailable", "team": id, "start": datetime, "end": datetime}
            {"kind": "assign", "job": id, "team": id}
    """
    names = {t.id: t.name for t in snapshot.teams}
    refs = {j.id: j.reference for j in snapshot.jobs}
    kind = change["kind"]
    if kind == "drop":
        jobs = tuple(
            j.model_copy(update={"state": "cancelled"}) if j.id == change["job"] else j
            for j in snapshot.jobs
        )
        # A cancelled job cannot stay frozen on its truck.
        locks = tuple(lock for lock in snapshot.locks if lock.job_id != change["job"])
        modified = snapshot.model_copy(update={"jobs": jobs, "locks": locks})
        return (
            modified,
            f"Job {refs[change['job']]} is cancelled",
            f"أُلغيت الشحنة {refs[change['job']]}",
        )
    if kind == "unavailable":
        team = next(t for t in snapshot.teams if t.id == change["team"])
        window = Window(start=change["start"], end=change["end"])
        rule = Rule(
            id="what-if-unavailable",
            kind="resource_unavailable",
            resource_id=team.tractor_id,
            window=window,
            source_text="What-if",
        )
        modified = snapshot.model_copy(update={"rules": (*snapshot.rules, rule)})
        return (
            modified,
            f"{team.name} is unavailable from {_when(window.start)} to {_when(window.end)} (Riyadh)",
            f"أصبحت {team.name} غير متاحة من {_numeric(window.start)} إلى {_numeric(window.end)} "
            "(بتوقيت الرياض)",
        )
    if kind == "assign":
        locks = tuple(lock for lock in snapshot.locks if lock.job_id != change["job"])
        lock = AssignmentLock(job_id=change["job"], team_id=change["team"])
        modified = snapshot.model_copy(update={"locks": (*locks, lock)})
        return (
            modified,
            f"Job {refs[change['job']]} must go to {names[change['team']]}",
            f"يجب إسناد الشحنة {refs[change['job']]} إلى {names[change['team']]}",
        )
    raise ValueError(f"Unknown what-if: {kind}")


def _time(value: Any) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(value)


def repair(modified: Snapshot, plan: Plan, change: dict[str, Any]) -> Plan:
    """The smallest sensible change to ``plan`` under ``modified``: deterministic.

    Every route is kept; jobs the change makes impossible come off their truck
    (for an unavailable truck: only the jobs overlapping that time), and those,
    plus any contract job the freed capacity can now take, are inserted where
    they cost least. Spot loads are only put back if the plan had taken them.
    """
    routes = routes_of(plan)
    if change["kind"] == "unavailable":
        start, end = _time(change["start"]), _time(change["end"])
        clashing = {
            a.job_id
            for a in plan.assignments
            if a.team_id == change["team"] and a.pickup_at < end and a.released_at > start
        }
        routes[change["team"]] = [j for j in routes.get(change["team"], []) if j not in clashing]
    engine = Engine(modified, 1)
    search = Search(engine)
    search.load(routes)
    taken = {a.job_id for a in plan.assignments}
    search.recreate([j for j in search.confirmed if j not in search.solution.where])
    search.recreate([j for j in search.offered if j in taken and j not in search.solution.where])
    return validate_plan(modified, materialize(engine, search.solution))


def what_if(
    snapshot: Snapshot,
    plan: Plan,
    change: dict[str, Any],
    *,
    method: Literal["repair", "replan"] = "repair",
    rounds: int = 3000,
    seed: int = 1,
    change_penalty_minor: int = 30_000,
) -> tuple[dict[str, Any], Snapshot, Plan]:
    """Compare the current plan with the plan under a hypothetical change.

    "repair" (default, deterministic, about a second): the current plan with the
    least change that makes it work, compared with the current plan itself.

    "replan" (an estimate, tens of seconds): two re-plans with the same effort,
    both starting from the current plan and penalizing moved jobs; a control
    without the change and one with it. The difference isolates the change from
    unrelated improvement, but search noise remains (about one job or a few
    hundred riyals on a 100-truck week).
    """
    names = {t.id: t.name for t in snapshot.teams}
    refs = {j.id: j.reference for j in snapshot.jobs}
    modified, description, description_ar = changed_situation(snapshot, change)
    if method == "repair":
        before, after, before_snapshot = plan, repair(modified, plan, change), snapshot
    else:
        current = {a.job_id: a.team_id for a in plan.assignments}
        steady = {"previous": current, "change_penalty_minor": change_penalty_minor}
        before_snapshot = snapshot.model_copy(update=steady)
        modified = modified.model_copy(update=steady)
        before = plan_lns(before_snapshot, seed=seed, rounds=rounds, initial=routes_of(plan))
        after = plan_lns(modified, seed=seed, rounds=rounds, initial=routes_of(plan))
    for planned in (before, after):
        if planned.outcome == "model_invalid":
            raise WhatIfRefused("; ".join(f.message for f in planned.findings[:3]))
    if change["kind"] == "assign" and not any(
        a.job_id == change["job"] and a.team_id == change["team"] for a in after.assignments
    ):
        raise WhatIfImpossible(
            f"{names[change['team']]} cannot take {refs[change['job']]}, even with its other "
            "unfrozen work moved to other trucks: the time windows, its days off or the "
            "driving-hours rules leave no room.",
            f"لا تستطيع {names[change['team']]} تنفيذ الشحنة {refs[change['job']]} حتى بعد نقل "
            "أعمالها غير المثبّتة إلى شاحنات أخرى: النوافذ الزمنية أو أيام إجازتها أو قواعد "
            "ساعات القيادة لا تسمح بذلك.",
        )
    if not after.valid:
        reasons = "; ".join(f.message for f in after.findings[:3])
        raise WhatIfImpossible(
            f"No valid plan exists with this change: {reasons}",
            f"لا توجد خطة صالحة مع هذا التغيير: {reasons}",
        )
    changes = diff_plans(before, after)

    def numbers(snap: Snapshot, p: Plan) -> dict[str, Any]:
        confirmed = {j.id for j in snap.jobs if j.state == "confirmed"}
        offered = {j.id for j in snap.jobs if j.state == "offered"}
        served = {a.job_id for a in p.assignments}
        c = p.costs
        return {
            "contract_jobs_served": len(served & confirmed),
            "offers_taken": len(served & offered),
            "cost_sar": _sar(c.total_minor) if c and c.total_minor is not None else None,
            "contribution_sar": (
                _sar(c.revenue_minor - c.total_minor)
                if c and c.revenue_minor is not None and c.total_minor is not None
                else None
            ),
            "empty_km": round(c.empty_distance_m / 1000) if c else None,
        }

    before_numbers, after_numbers = numbers(before_snapshot, before), numbers(modified, after)
    was_served = {a.job_id for a in before.assignments}
    now_served = {a.job_id for a in after.assignments}
    facts = {
        "question": "what_if",
        "method": method,
        "change": description,
        "change_ar": description_ar,
        "before": before_numbers,
        "after": after_numbers,
        "difference": {
            k: after_numbers[k] - before_numbers[k]
            for k in before_numbers
            if before_numbers[k] is not None and after_numbers[k] is not None
        },
        "new_plan_valid": after.valid,
        "jobs_moved_to_another_truck": [
            f"{refs.get(j, j)}: {names.get(a, a)} -> {names.get(b, b)}"
            for j, a, b in changes.moved[:10]
        ],
        "jobs_moved_count": len(changes.moved),
        "jobs_no_longer_served": sorted(
            refs[j] for j in was_served - now_served if j in refs and j != change.get("job")
        ),
        "jobs_newly_served": sorted(refs[j] for j in now_served - was_served if j in refs),
        "trucks_whose_plan_changes": len(changes.teams_to_notify),
    }
    return facts, modified, after


INSTRUCTIONS = """You explain a computed freight plan to a Saudi truck dispatcher.
Use ONLY the facts in the JSON input. Quote numbers exactly as given; never estimate,
add or invent costs, savings, reasons or causes. If the facts do not answer something,
say so briefly. Money is in SAR. Keep it under 120 words, plain and practical, no headings.
For a what-if, "method" says how it was computed: "repair" is the least change to the
current plan (exact), "replan" a fresh re-plan (an estimate with some search noise); say which.
Write in {language}. In Arabic use clear Modern Standard Arabic and the Arabic site names
given in the facts where present."""


def narrate(facts: dict[str, Any], language: Language = "en") -> tuple[str, str]:
    """Explanation text and its source: the language model, or the built-in template."""
    settings = get_settings()
    if settings.ai_configured and settings.openai_api_key is not None:
        try:
            with OpenAI(
                api_key=settings.openai_api_key.get_secret_value(), timeout=30, max_retries=0
            ) as client:
                response = client.responses.create(
                    model=settings.openai_model_rules,
                    instructions=INSTRUCTIONS.format(
                        language="Arabic" if language == "ar" else "English"
                    ),
                    input=json.dumps(facts, ensure_ascii=False),
                    store=False,
                    max_output_tokens=900,
                    reasoning=(
                        {"effort": settings.openai_reasoning_effort}
                        if settings.openai_reasoning_effort
                        else omit
                    ),
                )
            text = (response.output_text or "").strip()
            if response.status == "completed" and text:
                return text, f"AI ({response.model})"
        except OpenAIError:
            pass
    return template(facts, language), "template"


def template(facts: dict[str, Any], language: Language = "en") -> str:
    """A plain, always-available explanation built directly from the facts."""
    ar = language == "ar"
    if facts["question"] == "why":
        job = facts["job"]
        assigned = facts.get("assigned")
        alternatives = facts["alternatives"]
        cannot = facts["trucks_that_cannot_take_it"]
        if ar:
            lines = [f"الشحنة {job['reference']} من {job['from_ar']} إلى {job['to_ar']}."]
            if assigned:
                lines.append(
                    f"أُسندت إلى {assigned['truck']} بتكلفة إضافية {assigned['extra_cost_sar']} ريال."
                )
                if alternatives:
                    best = alternatives[0]
                    lines.append(
                        f"أفضل بديل هو {best['truck']}، وهو أغلى بـ{best['more_than_chosen_sar']} ريال."
                    )
            else:
                lines.append("لم تُسند إلى أي شاحنة في هذه الخطة.")
            if cannot:
                lines.append(f"لا تستطيع {sum(cannot.values())} شاحنة أخرى تنفيذها.")
            return " ".join(lines)
        lines = [f"{job['reference']} runs {job['from']} → {job['to']}."]
        if assigned:
            lines.append(
                f"It is on {assigned['truck']}, adding SAR {assigned['extra_cost_sar']} to that truck's day."
            )
            if alternatives:
                best = alternatives[0]
                lines.append(
                    f"The best alternative, {best['truck']}, would cost SAR "
                    f"{best['more_than_chosen_sar']} more."
                )
        else:
            lines.append("No truck takes it in this plan.")
        if cannot:
            details = ", ".join(f"{n} {reason}" for reason, n in cannot.items())
            lines.append(f"Other trucks cannot take it: {details}.")
        return " ".join(lines)
    d, after = facts["difference"], facts["after"]
    repaired = facts.get("method", "repair") == "repair"
    if ar:
        lead = "بأقل تعديل على الخطة الحالية" if repaired else "بإعادة تخطيط كاملة (تقدير)"
        return (
            f"{lead}، إذا {facts['change_ar']}: يتغير هامش المساهمة بمقدار {d.get('contribution_sar', 0)} ريال، "
            f"وعدد الشحنات المتعاقد عليها المنفذة بمقدار {d.get('contract_jobs_served', 0)}. "
            f"تنتقل {facts['jobs_moved_count']} شحنة إلى شاحنات أخرى، وتتغير خطط "
            f"{facts['trucks_whose_plan_changes']} شاحنة."
        )
    lost = facts["jobs_no_longer_served"]
    total = after.get("contribution_sar")
    lead = "With the least change to today's plan" if repaired else "With a full re-plan (estimate)"
    return (
        f"{lead}, if {facts['change'][0].lower() + facts['change'][1:]}: contribution changes by SAR "
        f"{d.get('contribution_sar', 0):,}{f' (to SAR {total:,})' if total is not None else ''}, contract jobs "
        f"served by {d.get('contract_jobs_served', 0)}. {facts['jobs_moved_count']} "
        f"{'job moves' if facts['jobs_moved_count'] == 1 else 'jobs move'} to another truck and "
        f"{facts['trucks_whose_plan_changes']} trucks' plans change."
        + (f" No longer served: {', '.join(lost)}." if lost else "")
    )
