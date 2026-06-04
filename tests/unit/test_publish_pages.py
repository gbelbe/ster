"""Unit tests for discovering and presenting published pages (publish screen)."""

from __future__ import annotations

from pathlib import Path


def _make_group(publish_dir: Path, group: str, *, html: bool = True, ttl: bool = True) -> None:
    d = publish_dir / group
    d.mkdir(parents=True, exist_ok=True)
    if ttl:
        (d / "onto.ttl").write_text("# ttl")
    if html:
        (d / "index.html").write_text("<html></html>")


# ── discover_published_pages ──────────────────────────────────────────────────


def test_discover_orders_dev_latest_then_versions(tmp_path):
    from ster.publish import discover_published_pages

    pub = tmp_path / "ontology"
    _make_group(pub, "dev")
    _make_group(pub, "latest")
    _make_group(pub, "v1.0.0")
    groups = [p.group for p in discover_published_pages(pub)]
    # de-duplicated, preserving order
    seen = list(dict.fromkeys(groups))
    assert seen == ["Dev", "Latest", "v1.0.0"]


def test_discover_versions_newest_first(tmp_path):
    from ster.publish import discover_published_pages

    pub = tmp_path / "ontology"
    for v in ("v1.0.0", "v1.2.0", "v1.1.0"):
        _make_group(pub, v)
    seen = list(dict.fromkeys(p.group for p in discover_published_pages(pub)))
    assert seen == ["v1.2.0", "v1.1.0", "v1.0.0"]


def test_discover_html_before_ttl(tmp_path):
    from ster.publish import discover_published_pages

    pub = tmp_path / "ontology"
    _make_group(pub, "dev")
    kinds = [p.kind for p in discover_published_pages(pub) if p.group == "Dev"]
    assert kinds == ["html", "ttl"]


def test_discover_skips_missing_groups(tmp_path):
    from ster.publish import discover_published_pages

    pub = tmp_path / "ontology"
    _make_group(pub, "latest")  # no dev/, no versions
    seen = list(dict.fromkeys(p.group for p in discover_published_pages(pub)))
    assert seen == ["Latest"]


def test_discover_empty_dir_returns_empty(tmp_path):
    from ster.publish import discover_published_pages

    assert discover_published_pages(tmp_path / "ontology") == []


def test_discover_ignores_non_version_dirs(tmp_path):
    from ster.publish import discover_published_pages

    pub = tmp_path / "ontology"
    _make_group(pub, "drafts")  # not dev/latest/v*
    _make_group(pub, "v2.0.0")
    seen = list(dict.fromkeys(p.group for p in discover_published_pages(pub)))
    assert seen == ["v2.0.0"]


def test_discover_group_with_only_ttl(tmp_path):
    from ster.publish import discover_published_pages

    pub = tmp_path / "ontology"
    _make_group(pub, "dev", html=False)  # ttl only
    kinds = [p.kind for p in discover_published_pages(pub) if p.group == "Dev"]
    assert kinds == ["ttl"]


# ── page_url ──────────────────────────────────────────────────────────────────


def test_page_url_served_when_base_url(tmp_path):
    from ster.publish import page_url

    pub = tmp_path / "ontology"
    p = pub / "latest" / "index.html"
    p.parent.mkdir(parents=True)
    p.write_text("x")
    url = page_url("http://127.0.0.1:8765", pub, p)
    assert url == "http://127.0.0.1:8765/ontology/latest/index.html"


def test_page_url_file_fallback_when_no_base(tmp_path):
    from ster.publish import page_url

    pub = tmp_path / "ontology"
    p = pub / "dev" / "onto.ttl"
    p.parent.mkdir(parents=True)
    p.write_text("x")
    url = page_url(None, pub, p)
    assert url == p.as_uri()
    assert url.startswith("file://")


# ── build_publish_menu ────────────────────────────────────────────────────────


def test_menu_first_row_publishes_stable(tmp_path):
    from ster.publish import build_publish_menu, discover_published_pages

    pub = tmp_path / "ontology"
    _make_group(pub, "latest")
    rows = build_publish_menu(discover_published_pages(pub), "http://h", pub)
    assert rows[0].action == "publish_stable"
    assert rows[0].url is None


def test_menu_lists_pages_as_full_urls(tmp_path):
    from ster.publish import build_publish_menu, discover_published_pages

    pub = tmp_path / "ontology"
    _make_group(pub, "latest")
    rows = build_publish_menu(discover_published_pages(pub), "http://127.0.0.1:8765", pub)
    open_rows = [r for r in rows if r.action == "open"]
    assert open_rows
    for r in open_rows:
        assert r.url is not None
        assert r.url in r.label
        assert r.url.startswith("http://127.0.0.1:8765/ontology/")


def test_menu_with_no_pages_only_has_action(tmp_path):
    from ster.publish import build_publish_menu, discover_published_pages

    pub = tmp_path / "ontology"  # nothing published
    rows = build_publish_menu(discover_published_pages(pub), "http://h", pub)
    assert len(rows) == 1
    assert rows[0].action == "publish_stable"
