"""Scores and ranks candidates: score = cost + w * P(miss deadline) * AOG cost.

Risk climbs linearly as the slack between estimated arrival and the
deadline shrinks, and hits 1.0 once there's no slack left at all.
"""

from dataclasses import dataclass
from datetime import datetime

from app.models import Plan, PlanStatus
from app.planner.candidates import Candidate

AOG_COST = 50_000.0
RISK_WEIGHT = 1.0
RISK_BUFFER_HOURS = 24.0


@dataclass
class ScoredCandidate:
    candidate: Candidate
    risk_score: float
    score: float


def risk_of_slack(slack_hours: float) -> float:
    if slack_hours <= 0:
        return 1.0
    return max(0.0, min(1.0, 1.0 - slack_hours / RISK_BUFFER_HOURS))


def score_candidate(candidate: Candidate, deadline: datetime) -> ScoredCandidate:
    slack_hours = (deadline - candidate.eta).total_seconds() / 3600
    risk = risk_of_slack(slack_hours)
    score = candidate.cost + RISK_WEIGHT * risk * AOG_COST
    return ScoredCandidate(candidate=candidate, risk_score=risk, score=score)


def rank_candidates(candidates: list[Candidate], deadline: datetime) -> list[ScoredCandidate]:
    scored = [score_candidate(c, deadline) for c in candidates]
    return sorted(scored, key=lambda s: s.score)


def pick_best(candidates: list[Candidate], deadline: datetime) -> ScoredCandidate | None:
    ranked = rank_candidates(candidates, deadline)
    return ranked[0] if ranked else None


def to_plan(installed_serial: str, scored: ScoredCandidate, status: PlanStatus = PlanStatus.proposed) -> Plan:
    c = scored.candidate
    return Plan(
        installed_serial=installed_serial,
        option=c.option,
        source=c.source,
        flight_number=c.flight_number,
        cost=c.cost,
        risk_score=scored.risk_score,
        status=status,
        reason=c.detail,
    )
