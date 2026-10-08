"""Which agent, and which model, made the calls a trace records.

The agent says who it is twice over without being asked: every HTTP request carries a ``User-Agent`` such as
``claude-code/2.1.292`` or ``opencode/1.18.34``. The model is not in any request; a client that can set MCP ``_meta``
may name it (and itself) in ``com.adeo/agent-name``, ``-version`` and ``-model``, and the page that ran an agent reports
the model with the answer. What is known goes into the run's ``agent`` payload, and PROV-O carries it from there.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

META_PREFIX = "com.adeo/agent-"
NAME, VERSION, MODEL = "name", "version", "model"
_FIELDS = (NAME, VERSION, MODEL)
_MAX = 128
_PRODUCT = re.compile(r"^([A-Za-z][\w.\-]{0,63})/([\w.+\-]{1,32})")
# Libraries every script and browser identifies as: they say how a request was made, not which agent made it.
_GENERIC = frozenset(
    {
        "mozilla",
        "python-requests",
        "python-httpx",
        "python-urllib",
        "curl",
        "node",
        "undici",
        "okhttp",
        "go-http-client",
    }
)


def from_user_agent(user_agent: str | None) -> dict[str, str]:
    """``{"name", "version"}`` from the first product of a User-Agent header; empty for a generic client."""
    found = _PRODUCT.match((user_agent or "").strip())
    if not found or found.group(1).lower() in _GENERIC:
        return {}
    return {NAME: found.group(1), VERSION: found.group(2)}


def from_meta(metadata: Mapping[str, Any]) -> dict[str, str]:
    """The agent fields a client named in its request ``_meta``; anything that is not a short string is dropped."""
    out: dict[str, str] = {}
    for field in _FIELDS:
        value = metadata.get(META_PREFIX + field)
        if isinstance(value, str) and value.strip() and len(value) <= _MAX:
            out[field] = value.strip()
    return out


def agent_of(user_agent: str | None, metadata: Mapping[str, Any]) -> dict[str, str] | None:
    """What is known about the caller: its own words in ``_meta`` over what its User-Agent says. None when neither speaks."""
    named = from_meta(metadata)
    known = from_user_agent(user_agent)
    # a name given in _meta replaces the User-Agent's, and the version that went with that name with it
    renamed = NAME in named and VERSION not in named
    merged = {**known, **named, VERSION: ""} if renamed else {**known, **named}
    return {k: v for k, v in merged.items() if v} or None


def with_answer(
    agent: dict[str, str] | None, answer: Mapping[str, Any] | None
) -> dict[str, str] | None:
    """*agent*, completed from the answer record of the run: the model, and the agent's name when no request gave one."""
    if not answer:
        return agent
    completed = dict(agent or {})
    for field, reported in ((MODEL, answer.get(MODEL)), (NAME, answer.get("agent"))):
        if isinstance(reported, str) and reported.strip() and field not in completed:
            completed[field] = reported.strip()
    return completed or None
