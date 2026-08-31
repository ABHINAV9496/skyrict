"""ai-agent account-code suggestion feature (SKY-56/SKY-64, option B).

Maps a free-text transaction description to the tenant's actual chart of
accounts via an LLM. Core sends the description + the tenant's account list;
this service asks the LLM to pick the single best account code/name and
return strict JSON. Any unusable outcome (invalid JSON, missing fields, LLM
failure) is an *abstention* -> ``None``, never a hard error — core falls back
to its deterministic matcher.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AccountOption:
    code: str
    name: str


@dataclass(frozen=True, slots=True)
class SuggestRequest:
    description: str
    accounts: list[AccountOption]


@dataclass(frozen=True, slots=True)
class AccountSuggestion:
    suggested_code: str
    suggested_name: str
    confidence: float
    reasoning: str
    model_used: str
