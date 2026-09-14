"""The graph-viewer thresholds: defaults, persistence, and reaching the page.

Every threshold the viewer uses is a number someone might need to change — the
right value depends on the ontology and the machine — so they live in config
(`ster setup` → Graph Viz) rather than in constants nobody can reach.

Two hazards these pin down. The config file now holds more than one section, so
saving one must not erase another; and a threshold of 0 or -1 would mean
"collapse everything", which reads as a typo rather than an intention.
"""

from __future__ import annotations

import json

import pytest

from ster import api_server as A


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    """Point the config at a temp file — never the developer's own."""
    path = tmp_path / "server_config.json"
    monkeypatch.setattr(A, "_SERVER_CONFIG_FILE", path)
    return path


def test_every_threshold_has_a_default(cfg):
    assert A.load_graph_viz_config() == A.GRAPH_VIZ_DEFAULTS


def test_a_saved_threshold_comes_back(cfg):
    A.save_graph_viz_config({"lodNodes": 1200})

    assert A.load_graph_viz_config()["lodNodes"] == 1200


def test_saving_one_threshold_leaves_the_others_at_their_defaults(cfg):
    A.save_graph_viz_config({"lodNodes": 1200})

    assert A.load_graph_viz_config()["lodEdges"] == A.GRAPH_VIZ_DEFAULTS["lodEdges"]


def test_saving_the_server_does_not_erase_the_thresholds(cfg):
    """The old save_server_config wrote the file whole, so it would have."""
    A.save_graph_viz_config({"lodNodes": 1200})
    A.save_server_config("http://127.0.0.1", 9999)

    assert A.load_graph_viz_config()["lodNodes"] == 1200


def test_saving_the_thresholds_does_not_erase_the_server(cfg):
    A.save_server_config("http://127.0.0.1", 9999)
    A.save_graph_viz_config({"lodNodes": 1200})

    assert A.load_server_config() == ("http://127.0.0.1", 9999)


@pytest.mark.parametrize("nonsense", [0, -1, "abc", None])
def test_a_threshold_that_cannot_mean_anything_falls_back(cfg, nonsense):
    cfg.write_text(json.dumps({"graphViz": {"lodNodes": nonsense}}))

    assert A.load_graph_viz_config()["lodNodes"] == A.GRAPH_VIZ_DEFAULTS["lodNodes"]


def test_an_unreadable_config_falls_back_rather_than_raising(cfg):
    cfg.write_text("{not json")

    assert A.load_graph_viz_config() == A.GRAPH_VIZ_DEFAULTS
