"""Context files inherit schema declarations from the editable file."""

from __future__ import annotations

from pathlib import Path

from ster.store import load


def test_context_instances_are_classified_by_main_file_schema(tmp_path: Path) -> None:
    main = tmp_path / "schema.ttl"
    context = tmp_path / "instances.ttl"
    main.write_text(
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "@prefix ex: <https://example.org/> .\n"
        "ex:Component a owl:Class .\n",
        encoding="utf-8",
    )
    context.write_text(
        "@prefix ex: <https://example.org/> .\n"
        "ex:item-1 a ex:Component .\n"
        "ex:item-2 a ex:Component .\n",
        encoding="utf-8",
    )

    taxonomy = load(main, context=[context])

    assert set(taxonomy.owl_individuals) >= {
        "https://example.org/item-1",
        "https://example.org/item-2",
    }
