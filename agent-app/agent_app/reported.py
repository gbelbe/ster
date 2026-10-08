"""What the agent said about itself while it ran, for the answer this page reports to ster."""

from __future__ import annotations

MODEL = "model"


def model_field(events: list[dict]) -> dict:
    """``{"model": name}`` when the agent's session event named the model it ran, else ``{}`` (so a body can spread it)."""
    for event in events:
        if event.get("e") == "session" and event.get(MODEL):
            return {MODEL: event[MODEL]}
    return {}
