"""Claude writes the one-line, plain-English reason on each plan. Without an
ANTHROPIC_API_KEY (or on any API error) this falls back to the planner's own
templated detail string, so the rest of the app works with zero setup.
"""

import logging
import os
from datetime import date
from typing import Optional

from app.planner.candidates import Candidate
from app.planner.score import ScoredCandidate

logger = logging.getLogger(__name__)

MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-5-5")
# Generous headroom: this model's response can carry formatting/reasoning
# overhead before any visible text, so a tight budget risks stop_reason
# "max_tokens" with zero text produced -- the one-sentence output itself
# is short, but the budget needs room for whatever precedes it.
MAX_TOKENS = 500

_client = None
_client_checked = False


def _get_client():
    global _client, _client_checked
    if _client_checked:
        return _client
    _client_checked = True

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.info("ANTHROPIC_API_KEY not set; using templated reason lines")
        return None
    try:
        from anthropic import Anthropic

        _client = Anthropic(api_key=api_key)
        logger.info("Anthropic client configured (key length=%d)", len(api_key))
    except Exception:
        logger.exception("Failed to construct Anthropic client; using templated reason lines")
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
        # content[0] isn't guaranteed to be the text block (e.g. a leading
        # thinking block), so scan for the first block that actually has text.
        text = next((block.text for block in response.content if getattr(block, "text", None)), None)
        if not text:
            logger.warning(
                "Claude response had no text block (stop_reason=%s, block types=%s); using templated reason line",
                getattr(response, "stop_reason", None),
                [type(b).__name__ for b in response.content],
            )
            return fallback
        return text.strip()
    except Exception:
        logger.exception("Claude reason-line call failed; using templated reason line")
        return fallback
