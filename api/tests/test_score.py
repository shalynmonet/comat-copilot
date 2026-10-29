"""Covers score.py's STD bump risk: an STD-priority candidate's score
goes up by the configured bump risk, MRD/AOG/no-priority candidates are
unaffected -- scoring stays exactly as it was before this was added.
"""

from datetime import datetime, timedelta

from app.config import load_private_codes
from app.models import PlanOption, Priority
from app.planner.candidates import Candidate
from app.planner.score import AOG_COST, score_candidate

NOW = datetime(2026, 11, 1, 8, 0)
DEADLINE = NOW + timedelta(hours=48)

CANDIDATE = Candidate(
    option=PlanOption.comat,
    source="DFW",
    flight_number="EV1",
    cost=25.0,
    eta=NOW + timedelta(hours=12),  # comfortably on time -> risk ~0
    detail="test candidate",
)


def test_no_priority_behaves_exactly_as_before():
    scored = score_candidate(CANDIDATE, DEADLINE)
    assert scored.score == CANDIDATE.cost + scored.risk_score * AOG_COST


def test_std_adds_the_configured_bump_risk():
    baseline = score_candidate(CANDIDATE, DEADLINE, priority=None)
    std_scored = score_candidate(CANDIDATE, DEADLINE, priority=Priority.std)

    bump_risk = load_private_codes().std_bump_risk
    assert std_scored.score == baseline.score + bump_risk * AOG_COST


def test_mrd_and_aog_add_no_bump_risk():
    baseline = score_candidate(CANDIDATE, DEADLINE, priority=None)
    mrd_scored = score_candidate(CANDIDATE, DEADLINE, priority=Priority.mrd)
    aog_scored = score_candidate(CANDIDATE, DEADLINE, priority=Priority.aog)

    assert mrd_scored.score == baseline.score
    assert aog_scored.score == baseline.score
