"""Command-line tools for inspecting and materialising query traces."""

from __future__ import annotations

import argparse
from pathlib import Path

from .jsonl import read_events
from .materialize import materialize_events
from .validation import validate_events


def main() -> None:
    parser = argparse.ArgumentParser(prog="ster-trace")
    commands = parser.add_subparsers(dest="command", required=True)

    for name in ("inspect", "validate"):
        command = commands.add_parser(name)
        command.add_argument("input", type=Path)

    materialize = commands.add_parser("materialize")
    materialize.add_argument("input", type=Path)
    materialize.add_argument("--output", type=Path, required=True)

    args = parser.parse_args()
    events = list(read_events(args.input))
    errors = validate_events(events)
    if args.command == "validate":
        if errors:
            parser.error("; ".join(errors))
        print(f"valid trace: {len(events)} events")
        return
    if errors:
        parser.error("; ".join(errors))
    if args.command == "inspect":
        _inspect(events)
        return
    dataset = materialize_events(events)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    dataset.serialize(destination=args.output, format="trig")


def _inspect(events) -> None:
    first, last = events[0], events[-1]
    print(f"Run: {first.run_id}")
    print(f"Trace: {first.trace_id}")
    print(f"Question: {first.payload.get('question', '')}")
    print(f"Started: {first.timestamp}")
    print(f"Finished: {last.timestamp}")
    print(f"Events: {len(events)}")
    print(f"Steps: {len({event.step_id for event in events if event.step_id})}")


if __name__ == "__main__":
    main()
