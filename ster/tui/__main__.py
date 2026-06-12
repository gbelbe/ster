"""``python -m ster.tui [ontology.ttl]`` — launch the browser (defaults to the demo)."""

from __future__ import annotations

import sys
from pathlib import Path

from ster import store

from . import launch


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    path = Path(args[0]) if args else Path(__file__).with_name("demo.ttl")
    launch(store.load(path), source=path.name)


if __name__ == "__main__":
    main()
