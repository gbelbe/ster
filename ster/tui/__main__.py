"""Entry point: ``python -m ster.tui [ontology.ttl]`` (defaults to the demo)."""

from __future__ import annotations

import sys
from pathlib import Path

from ster import store

from .app import OntologyApp


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    path = Path(args[0]) if args else Path(__file__).with_name("demo.ttl")
    taxonomy = store.load(path)
    OntologyApp(taxonomy, source=path.name).run()


if __name__ == "__main__":
    main()
