"""Out-of-range picks in the external-ontologies screen — each of the three
"pick a number" prompts (add / refresh / delete) must bail out on an invalid
index instead of falling through to the destructive/network step that follows.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from ster import ext_ontologies_ui
from ster.ontology_imports import COMMON_ONTOLOGIES


def test_action_add_rejects_an_out_of_range_number():
    out_of_range = str(len(COMMON_ONTOLOGIES) + 1)
    with (
        patch("rich.prompt.Prompt.ask", return_value=out_of_range),
        patch.object(ext_ontologies_ui, "fetch_ontology") as fetch,
        patch.object(ext_ontologies_ui, "add_namespace_to_taxonomy") as register,
    ):
        ext_ontologies_ui._action_add(None)
    fetch.assert_not_called()
    register.assert_not_called()


def test_action_refresh_rejects_an_out_of_range_number():
    cached = [("http://example.org/", Path("/tmp/cached-does-not-matter.ttl"), 3)]
    with (
        patch("rich.prompt.Prompt.ask", return_value="99"),
        patch.object(ext_ontologies_ui, "fetch_ontology") as fetch,
    ):
        ext_ontologies_ui._action_refresh(cached)
    fetch.assert_not_called()


def test_action_delete_rejects_an_out_of_range_number():
    fake_path = MagicMock(spec=Path)
    cached = [("http://example.org/", fake_path, 3)]
    with (
        patch("rich.prompt.Prompt.ask", return_value="99"),
        patch("rich.prompt.Confirm.ask") as confirm,
    ):
        ext_ontologies_ui._action_delete(cached)
    confirm.assert_not_called()
    fake_path.unlink.assert_not_called()
