"""A conversation that outlives its graph: the agent starts afresh on the new one instead of trusting old facts.

An agent's session holds what it learned about the graph (classes, namespaces, counts). When ster is relaunched on
another file, a follow-up that resumes that session reuses the old namespace in its first query and finds nothing.
The page already says so in a banner; this makes the follow-up itself safe: it starts a new agent session and is
told the graph changed.
"""

from __future__ import annotations

GRAPH, SESSION, MESSAGES, AGENT_PROMPT, FRESH = (
    "graph",
    "session_id",
    "messages",
    "agent_prompt",
    "fresh_session",
)
FINGERPRINT, TURNS = "fingerprint", "turns"


def changed(turns: list[dict], fingerprint: str | None) -> bool:
    """True when the graph now served is not the one the conversation's last answered turn was about."""
    last = next((t for t in reversed(turns) if t.get(GRAPH)), None)
    return bool(last and fingerprint and last[GRAPH] != fingerprint)


def name_of(graph: dict | None) -> str:
    """What to call the graph in a note: its title, else its ontology, else its file, with its size."""
    graph = graph or {}
    name = (
        graph.get("title") or graph.get("ontology_uri") or graph.get("file") or "a different graph"
    )
    triples = graph.get("triples")
    return f"{name} ({triples} triples)" if triples is not None else str(name)


def note_for(graph: dict | None) -> str:
    """The line put before the question when the graph changed: not to reuse what the old session knew."""
    return (
        f"[Note from the page: the graph ster serves changed since the previous question; it is now {name_of(graph)}. "
        "Earlier classes, namespaces, counts and answers in this conversation were about another graph: do not reuse "
        "them, and call get_overview and get_vocabulary again before querying.]"
    )


def start_afresh(conv: dict, turn: dict, graph: dict | None) -> None:
    """Make *turn* start a new agent session: forget the old session and transcript, and tell the agent why."""
    conv[SESSION] = None
    conv[MESSAGES] = []
    turn[AGENT_PROMPT] = f"{note_for(graph)}\n\n{turn['prompt']}"
    turn[FRESH] = {GRAPH: (graph or {}).get(FINGERPRINT), "name": name_of(graph)}


def prompt_of(turn: dict) -> str:
    """What the agent is asked for this turn: the question, with the note when the session started afresh."""
    return turn.get(AGENT_PROMPT) or turn["prompt"]


def begin(conv: dict, turn: dict, served: dict) -> None:
    """Called as a turn starts, with what ster serves (see ``ster_state``): when it is not the graph the
    conversation was about, start afresh."""
    graph = served.get(GRAPH)
    if changed(conv[TURNS], (graph or {}).get(FINGERPRINT)):
        start_afresh(conv, turn, graph)
