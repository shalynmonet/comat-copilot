"""Claude writes the reason line, but the app must work with zero setup:
no ANTHROPIC_API_KEY, or any error talking to the API, falls back to the
planner's own templated detail string.
"""

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from app.ai import explain
from app.ai.explain import explain_plan
from app.models import PlanOption
from app.planner.candidates import Candidate
from app.planner.score import ScoredCandidate

CHOSEN = ScoredCandidate(
    candidate=Candidate(
        option=PlanOption.comat,
        source="DFW",
        flight_number="EV2301",
        cost=25.0,
        eta=datetime(2026, 10, 28, 20, 25),
        detail="ride flight EV2301 from DFW, arrives 20:25",
    ),
    risk_score=0.0,
    score=25.0,
)
REJECTED = [
    Candidate(
        option=PlanOption.transfer,
        source="DFW",
        flight_number=None,
        cost=2482.22,
        eta=datetime(2026, 10, 29, 1, 12),
        detail="ground transfer from DFW, 811 mi, arrives 01:12",
    )
]


@pytest.fixture(autouse=True)
def reset_client_cache():
    explain._client = None
    explain._client_checked = False
    yield
    explain._client = None
    explain._client_checked = False


def test_falls_back_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = explain_plan(CHOSEN, REJECTED, "Crew Oxygen Bottle, 2L", "N501EV", "CVG", date(2026, 10, 30))
    assert result == CHOSEN.candidate.detail


def test_uses_claudes_text_when_available(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    fake_response = SimpleNamespace(content=[SimpleNamespace(text="  Flying the DFW spare in on EV2301 is free and arrives well ahead of the deadline.  ")])
    fake_client = SimpleNamespace(messages=SimpleNamespace(create=lambda **kwargs: fake_response))
    monkeypatch.setattr(explain, "_get_client", lambda: fake_client)

    result = explain_plan(CHOSEN, REJECTED, "Crew Oxygen Bottle, 2L", "N501EV", "CVG", date(2026, 10, 30))
    assert result == "Flying the DFW spare in on EV2301 is free and arrives well ahead of the deadline."


def test_falls_back_when_the_api_call_raises(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    def boom(**kwargs):
        raise RuntimeError("network error")

    fake_client = SimpleNamespace(messages=SimpleNamespace(create=boom))
    monkeypatch.setattr(explain, "_get_client", lambda: fake_client)

    result = explain_plan(CHOSEN, REJECTED, "Crew Oxygen Bottle, 2L", "N501EV", "CVG", date(2026, 10, 30))
    assert result == CHOSEN.candidate.detail


def test_prompt_includes_the_key_facts_and_no_invented_ones():
    prompt = explain._build_prompt(CHOSEN, REJECTED, "Crew Oxygen Bottle, 2L", "N501EV", "CVG", date(2026, 10, 30))
    assert "Crew Oxygen Bottle, 2L" in prompt
    assert "N501EV" in prompt
    assert "CVG" in prompt
    assert "EV2301" in prompt
    assert "$25" in prompt
    assert "ground transfer from DFW" in prompt
