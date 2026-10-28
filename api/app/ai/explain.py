"""Claude writes the one-line, plain-English reason on each plan. Without an
ANTHROPIC_API_KEY (or on any API error) this falls back to the planner's own
templated detail string, so the rest of the app works with zero setup.
"""

import os
from datetime import date
from typing import Optional

from app.planner.candidates import Candidate
from app.planner.score import ScoredCandidate

MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-5-5")
MAX_TOKENS = 100

_client = None
_client_checked = False


def _get_client():
    global _client, _client_checked
    if _client_checked:
        return _client
    _client_checked = True

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        from anthropic import Anthropic

        _client = Anthropic(api_key=api_key)
    except Exception:
        _client = None
    return _client


def _build_prompt(
    chosen: ScoredCandidate,
    rejected: list[Candidate],
    part_description: str,
    tail_number: str,
    station: str,
    deadline: date,
) -> str:
    via_flight = f" via flight {chosen.candidate.flight_number}" if chosen.candidate.flight_number else ""
    rejected_lines = "\n".join(f"- {c.option.value} from {c.source}: {c.detail}" for c in rejected) or "none"

    return f"""A regional airline's maintenance planner needs a one-sentence, plain-English reason for a parts-logistics decision. Be concise (under 30 words), confident, and only use the numbers already given below -- never invent facts.

Part: {part_description} on tail {tail_number}, needed at {station} by {deadline.isoformat()}.
Chosen option: {chosen.candidate.option.value} from {chosen.candidate.source}{via_flight}, cost ${chosen.candidate.cost:.0f}, risk {chosen.risk_score:.0%}.
Rejected alternatives:
{rejected_lines}

Write only the one-sentence reason, no preamble."""


def explain_plan(
    chosen: ScoredCandidate,
    rejected: list[Candidate],
    part_description: str,
    tail_number: str,
    station: str,
    deadline: date,
) -> str:
    fallback = chosen.candidate.detail

    client = _get_client()
    if client is None:
        return fallback

    prompt = _build_prompt(chosen, rejected, part_description, tail_number, station, deadline)
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        return text or fallback
    except Exception:
        return fallback
