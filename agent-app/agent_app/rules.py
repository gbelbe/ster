"""Turning an agent's own event stream into the neutral protocol (runner.py) with rules written in its recipe.

No code per agent: a recipe lists rules, this module applies them to each line the agent prints.

    {"when": {"type": "result"}, "emit": {"e": "done", "answer": "$.result", "status": {"if": "$.is_error", "then": "error", "else": "completed"}}}

A rule has a `when` (every listed path must match; a list means "any of"; `{"exists": true}` only asks for presence)
and one or more actions, run in this order:

    set      {"step": "$.event.message.id"}                remember a value for later lines
    begin    {"key": "$.event.index", "fields": {...}}     start collecting fragments under a key
    append   {"key": "$.event.index", "text": "$.…"}       add a fragment (JSON arrives in pieces)
    each     "$.message.content"  (+ "where": {...})        run `emit` once per item, with `$` meaning the item
    emit     {...} or [{...}, ...]                          print neutral events
    flush    {"key": "…", "emit": {...}}                    print events built from what was collected, then forget it

Values inside `emit`, `set` and `fields`:

    "$.a.b[0].c"                       a field of the line (absent: the key is left out, never written as null)
    "@name"                            a field saved by `begin` (inside `flush`)
    {"state": "step"}                  a value remembered by `set`
    {"any": [value, value]}            the first one that is present
    {"join": "$.content[*].text"}      the texts of a list joined; a plain string stays as it is
    {"if": "$.x", "then": v, "else": v}   a choice on whether a field is present and truthy
    {"json": "buffer"}                 what `append` collected, parsed (kept as {"raw": text} if it is not JSON)
    anything else                      itself; objects and lists are filled in recursively
"""

from __future__ import annotations

import json
import re
from typing import Any

_MISSING = object()
_PATH = re.compile(r"^\$(?:\.(.+))?$")


def _walk(node: Any, parts: list[str]) -> Any:
    for i, part in enumerate(parts):
        m = re.fullmatch(r"([^\[\]]*)\[(\*|\d+)\]", part)
        name, index = (m.group(1), m.group(2)) if m else (part, None)
        if name:
            if not isinstance(node, dict) or name not in node:
                return _MISSING
            node = node[name]
        if index is None:
            continue
        if not isinstance(node, list):
            return _MISSING
        if index == "*":  # project the rest of the path over every item
            rest = parts[i + 1 :]
            return [
                v
                for v in (_walk(item, rest) if rest else item for item in node)
                if v is not _MISSING
            ]
        if int(index) >= len(node):
            return _MISSING
        node = node[int(index)]
    return node


def get(line: Any, path: str) -> Any:
    """A `$.a.b[0].c` path in `line`; `_MISSING` when any step is absent."""
    m = _PATH.match(path)
    if not m:
        return _MISSING
    return line if m.group(1) is None else _walk(line, m.group(1).split("."))


def _truthy(v: Any) -> bool:
    return v is not _MISSING and v is not None and v is not False and v != "" and v != 0


class Rules:
    """A recipe's rule list plus the little memory it needs between lines."""

    def __init__(self, rules: list[dict]):
        self.rules = rules
        self.vars: dict[str, Any] = {}
        self.parts: dict[Any, dict] = {}  # key -> {"fields": {...}, "buffer": "..."}

    # ----------------------------------------------------------- values
    def value(self, expr: Any, line: Any, saved: dict | None = None) -> Any:
        if isinstance(expr, str):
            if expr.startswith("$"):
                return get(line, expr)
            if expr.startswith("@") and saved is not None:
                return saved["fields"].get(expr[1:], _MISSING)
            return expr
        if isinstance(expr, list):
            return [v for v in (self.value(e, line, saved) for e in expr) if v is not _MISSING]
        if not isinstance(expr, dict):
            return expr
        if "state" in expr:
            return self.vars.get(expr["state"], _MISSING)
        if "any" in expr:
            return next(
                (
                    v
                    for v in (self.value(e, line, saved) for e in expr["any"])
                    if v is not _MISSING and v is not None
                ),
                _MISSING,
            )
        if "join" in expr:
            v = get(line, expr["join"])
            if isinstance(v, list):
                return "".join(str(x) for x in v)
            return v
        if "if" in expr:
            cond = (
                get(line, expr["if"])
                if isinstance(expr["if"], str) and expr["if"].startswith("$")
                else self.value(expr["if"], line, saved)
            )
            return self.value(
                expr["then"] if _truthy(cond) else expr.get("else", _MISSING), line, saved
            )
        if "json" in expr:
            text = (saved or {}).get("buffer", "")
            try:
                return json.loads(text or "{}")
            except ValueError:
                return {"raw": text}
        return self.build(expr, line, saved)

    def build(self, template: dict, line: Any, saved: dict | None = None) -> dict:
        out = {}
        for key, expr in template.items():
            v = self.value(expr, line, saved)
            if v is not _MISSING and v is not None:
                out[key] = v
        return out

    # ----------------------------------------------------------- matching
    @staticmethod
    def matches(when: dict, line: Any) -> bool:
        for path, want in when.items():
            got = get(line, "$." + path)
            if isinstance(want, dict) and "exists" in want:
                if (got is not _MISSING) != bool(want["exists"]):
                    return False
            elif got is _MISSING or (got not in want if isinstance(want, list) else got != want):
                return False
        return True

    # ----------------------------------------------------------- applying
    def apply(self, line: Any) -> list[dict]:
        """The neutral events one line of the agent's output stands for (possibly none)."""
        events: list[dict] = []
        for rule in self.rules:
            if self.matches(rule.get("when", {}), line):
                events += self._apply_rule(rule, line)
        return events

    def _apply_rule(self, rule: dict, line: Any) -> list[dict]:
        """What one matching rule does with *line*: set variables, begin/append a block, emit, flush."""
        for name, val in (rule.get("set") or {}).items():
            v = self.value(val, line)
            if v is not _MISSING:
                self.vars[name] = v
        if "begin" in rule:
            key = get(line, rule["begin"]["key"])
            self.parts[key] = {
                "fields": self.build(rule["begin"].get("fields", {}), line),
                "buffer": "",
            }
        if "append" in rule:
            self._append(rule["append"], line)
        events = self._emit_each(rule, line) if "each" in rule else []
        if "each" not in rule and "emit" in rule:
            events = self._emit(rule["emit"], line)
        if "flush" in rule:
            saved = self.parts.pop(get(line, rule["flush"]["key"]), None)
            if saved is not None:  # a block that was never begun (text, say) has nothing to flush
                events += self._emit(rule["flush"]["emit"], line, saved)
        return events

    def _append(self, spec: dict, line: Any) -> None:
        key, text = get(line, spec["key"]), get(line, spec["text"])
        if key in self.parts and isinstance(text, str):
            self.parts[key]["buffer"] += text

    def _emit_each(self, rule: dict, line: Any) -> list[dict]:
        items = get(line, rule["each"])
        events: list[dict] = []
        for item in items if isinstance(items, list) else []:
            if self.matches(rule.get("where", {}), item):
                events += self._emit(rule.get("emit", []), item)
        return events

    def _emit(self, templates: Any, line: Any, saved: dict | None = None) -> list[dict]:
        return [
            self.build(t, line, saved)
            for t in (templates if isinstance(templates, list) else [templates])
        ]
