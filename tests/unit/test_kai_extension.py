"""Cross-browser compatibility checks for the kai-extension.

Rules validated:
- manifest_version 3 (required by both Chrome ≥88 and Firefox ≥109)
- browser_specific_settings.gecko present with id + strict_min_version ≥109 (Firefox)
- top-level "action" key, not "browser_action" (MV3 — both browsers)
- host_permissions is a top-level key, not nested inside permissions (MV3)
- popup.js uses only the chrome.* namespace — Firefox exposes this via its
  compatibility shim, so the same JS runs unmodified in both browsers
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_EXT = Path(__file__).parents[2] / "kai-extension"


def _manifest() -> dict:
    return json.loads((_EXT / "manifest.json").read_text())


def _popup_js() -> str:
    return (_EXT / "popup.js").read_text()


# ── manifest.json ─────────────────────────────────────────────────────────────


def test_manifest_version_is_3():
    assert _manifest()["manifest_version"] == 3


def test_manifest_has_action_not_browser_action():
    m = _manifest()
    assert "action" in m, "MV3 requires 'action', not 'browser_action'"
    assert "browser_action" not in m


def test_manifest_host_permissions_is_top_level():
    m = _manifest()
    assert "host_permissions" in m, "MV3 requires host_permissions at the top level"
    assert "host_permissions" not in m.get("permissions", [])


def test_manifest_has_gecko_id():
    gecko = _manifest().get("browser_specific_settings", {}).get("gecko", {})
    assert gecko.get("id"), "Firefox requires browser_specific_settings.gecko.id"


def test_manifest_gecko_min_version_supports_mv3():
    gecko = _manifest().get("browser_specific_settings", {}).get("gecko", {})
    raw = gecko.get("strict_min_version", "0")
    major = int(str(raw).split(".")[0])
    assert major >= 109, f"Firefox MV3 requires gecko strict_min_version ≥ 109, got {raw}"


# ── popup.js ──────────────────────────────────────────────────────────────────


def test_popup_js_uses_only_chrome_namespace():
    """The chrome.* shim works in Firefox; bare browser.* calls do not work in Chrome."""
    src = _popup_js()
    browser_calls = re.findall(r"\bbrowser\.\w+", src)
    assert not browser_calls, (
        f"popup.js uses Firefox-only 'browser.*' calls: {browser_calls}. "
        "Use 'chrome.*' instead — Firefox exposes it via its compatibility shim."
    )


def test_popup_js_references_chrome_storage():
    assert "chrome.storage" in _popup_js()


def test_popup_js_references_chrome_tabs():
    assert "chrome.tabs" in _popup_js()
