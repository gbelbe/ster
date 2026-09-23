"""The ``/timeline`` page — a navigable frieze of everything the graph dates.

Three layers, the separation :mod:`ster.viz_vowl` already keeps with Cytoscape:

* the **vendored library**, vis-timeline, downloaded once to ``~/.cache/ster``;
* the **application layer**, ``ster/assets/timeline_app.js``, versioned here and
  never overwritten by a library bump;
* the **data layer**, injected as ``window.__STER_TIMELINE__``.

vis-timeline rather than a charting library because a frieze is what it *is*:
zoom from the hour to the century, lanes, overlap stacking and — the reason it
wins for a knowledge graph — an item body that is plain HTML, so a thumbnail and
a label arrive from the metadata with no rendering code of ster's own.

It is also the first dependency ster vendors that needs a stylesheet, hence
:func:`_vis_style_tag` beside :func:`_vis_script_tag`.
"""

from __future__ import annotations

import functools
import html
import json

from .viz_shared import vendored

# Pinned, like the Cytoscape vendoring: a library that changes under a cached
# file is a bug report nobody can reproduce.
_VIS_VERSION = "8.5.4"
_VIS_JS_CDN = (
    f"https://cdnjs.cloudflare.com/ajax/libs/vis-timeline/{_VIS_VERSION}/"
    "vis-timeline-graph2d.min.js"
)
_VIS_CSS_CDN = (
    f"https://cdnjs.cloudflare.com/ajax/libs/vis-timeline/{_VIS_VERSION}/"
    "vis-timeline-graph2d.min.css"
)
_VIS_JS_CACHE = f"vis-timeline-{_VIS_VERSION}.js"
_VIS_CSS_CACHE = f"vis-timeline-{_VIS_VERSION}.css"

# The query the page opens with when none is given. Mirrors the map's default:
# ask for anything carrying the datatypes that announce a time, and let the
# server decide what each one means.
DEFAULT_TIMELINE_QUERY = """\
PREFIX xsd:  <http://www.w3.org/2001/XMLSchema#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT DISTINCT ?thing ?name
WHERE {
  ?thing ?whenProperty ?when .
  FILTER (datatype(?when) IN (xsd:date, xsd:dateTime, xsd:dateTimeStamp,
                              xsd:gYear, xsd:gYearMonth))
  OPTIONAL { ?thing rdfs:label ?name }
}
LIMIT 5000
"""


def _vis_script_tag() -> str:
    """Inline vis-timeline, or a CDN tag when it could not be cached."""
    source = vendored(_VIS_JS_CACHE, _VIS_JS_CDN)
    return f"<script>{source}</script>" if source else f'<script src="{_VIS_JS_CDN}"></script>'


def _vis_style_tag() -> str:
    """Inline vis-timeline's stylesheet, or a CDN link when it could not be cached."""
    source = vendored(_VIS_CSS_CACHE, _VIS_CSS_CDN)
    if source:
        return f"<style>{source}</style>"
    return f'<link rel="stylesheet" href="{_VIS_CSS_CDN}">'


@functools.lru_cache(maxsize=1)
def _app_js() -> str:
    """ster's own timeline application layer, from the versioned repo asset."""
    from importlib.resources import files  # noqa: PLC0415

    return (files("ster") / "assets" / "timeline_app.js").read_text(encoding="utf-8")


def render_timeline_html(query: str, token: str) -> str:
    """The ``/timeline`` page, primed with *query* and able to re-run it.

    The token is embedded rather than put in the URL, exactly as the map does:
    it keeps credentials out of browser history while letting the page call the
    server's own endpoints.
    """
    return (
        _PAGE.replace("__QUERY__", html.escape(query, quote=True))
        .replace("__VIS_CSS__", _vis_style_tag())
        .replace("__VIS_JS__", _vis_script_tag())
        .replace(
            "__DATA__",
            "<script>window.__STER_TIMELINE__=" + json.dumps({"token": token}) + ";</script>",
        )
        .replace("__APP_JS__", _app_js())
    )


_PAGE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>ster — timeline</title>
__VIS_CSS__
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#f1f5f9;color:#1e293b;font-family:system-ui,-apple-system,sans-serif;height:100vh;display:flex;flex-direction:column}
header{display:flex;align-items:center;gap:8px;padding:8px 12px;background:#f8fafc;border-bottom:1px solid #e2e8f0;flex-wrap:wrap}
header button{background:#fff;border:1px solid #cbd5e1;color:#475569;cursor:pointer;font-size:12px;padding:4px 10px;border-radius:5px}
header button:hover{background:#e2e8f0}
#status{font-size:11px;color:#64748b;margin-left:auto}
#lanes{display:flex;gap:5px;flex-wrap:wrap;padding:6px 12px;background:#f8fafc;border-bottom:1px solid #e2e8f0}
.ftbtn{background:transparent;border:1px solid #cbd5e1;color:#1e293b;border-radius:999px;cursor:pointer;font:inherit;font-size:11px;padding:2px 9px}
.ftbtn:hover{border-color:#1f5b80}
.ftbtn.on{background:#1f5b80;border-color:#1f5b80;color:#fff}
.fclear{border:0;background:none;color:#64748b;cursor:pointer;font:inherit;font-size:11px;text-decoration:underline}
#qbox{display:none;padding:8px 12px;background:#f8fafc;border-bottom:1px solid #e2e8f0}
#qbox.open{display:block}
header button.active{background:#1f5b80;border-color:#1f5b80;color:#fff}
#q{width:100%;height:120px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;border:1px solid #cbd5e1;border-radius:5px;padding:6px}
#main{flex:1;display:flex;min-height:0}
#tl{flex:1;background:#fff;min-width:0}
#panel{display:none;width:26vw;min-width:220px;max-width:400px;overflow-y:auto;background:#f8fafc;border-left:1px solid #e2e8f0;position:relative}
#panel-close{position:absolute;top:6px;right:6px;background:#f8fafc;border:1px solid #e2e8f0;color:#64748b;cursor:pointer;border-radius:4px;padding:2px 7px}
.dp{padding:14px}
.dp-h2{font-size:15px;font-weight:600;color:#0f172a;margin-bottom:3px}
.dp-uri{font-size:10px;color:#94a3b8;word-break:break-all;margin-bottom:10px}
.dp-row{display:flex;justify-content:space-between;padding:3px 0;border-bottom:1px solid #f1f5f9;font-size:11px}
.dp-row span:first-child{color:#64748b}
.dp-note{white-space:pre-wrap;font-size:11px;line-height:1.45;margin-top:10px;color:#334155;font-family:inherit}
.vis-item .thumb{height:22px;width:22px;object-fit:cover;border-radius:3px;vertical-align:middle;margin-right:5px}
.vis-item .lbl{font-weight:600}
.vis-item .pred{color:#64748b;font-size:10px;margin-left:6px}
.vis-item.interval{background:#dbeafe;border-color:#60a5fa}
.vis-item.instant{background:#fef3c7;border-color:#fbbf24}
/* PROV-O moments, last so they win over the instant/interval pair: the shape
   still says instant or interval, the colour says this is the record of a fact
   rather than the fact. */
.vis-item.provenance{background:#ede9fe;border-color:#a78bfa;color:#3b0764}
.vis-item.provenance .pred{color:#6d28d9}
</style>
</head>
<body>
<header>
  <strong style="font-size:13px">Timeline</strong>
   <button id="fit">Fit to data</button>
   <button id="toggle-q">Query</button>
   <button id="toggle-auxiliary">Provenance &amp; annotations</button>
   <button id="run">Run</button>
  <span id="status"></span>
</header>
<div id="qbox"><textarea id="q">__QUERY__</textarea></div>
<div id="lanes"></div>
<div id="main">
  <div id="tl"></div>
  <div id="panel"><button id="panel-close">×</button></div>
</div>
__VIS_JS__
__DATA__
<script>__APP_JS__</script>
</body>
</html>
"""
