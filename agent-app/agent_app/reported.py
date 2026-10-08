"""What the agent said about itself while it ran, for the answer this page reports to ster."""

from __future__ import annotations

MODEL = "model"


def model_field(events: list[dict]) -> dict:
    """``{"model": name}`` when the agent's session event named the model it ran, else ``{}`` (so a body can spread it)."""
    for event in events:
        if event.get("e") == "session" and event.get(MODEL):
            return {MODEL: event[MODEL]}
    return {}


ANSWER, ERROR = "answer", "error"


def error_fields(turn: dict) -> dict:
    """The turn's answer and error as reported: a turn that failed has no answer, so what went wrong is its answer."""
    failure = turn.get(ERROR)
    return {ANSWER: turn.get(ANSWER) or failure, ERROR: failure}


def keep_error(turn: dict, done: dict) -> None:
    """Remember on the turn why it failed, from the event that ended it."""
    turn[ERROR] = done.get(ERROR)
