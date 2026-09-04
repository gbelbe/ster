"""The command-palette (ctrl+p / ``/``) fuzzy search provider: jump to any
class, individual, or property by label."""

from __future__ import annotations

from functools import partial

from textual.command import Hit, Hits, Provider

from .. import data


class EntitySearch(Provider):
    """Fuzzy 'jump to any class / individual / property' command-palette provider."""

    async def startup(self) -> None:
        self._rows = self.app.search_rows  # type: ignore[attr-defined]

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        jump = self.app.jump_to  # type: ignore[attr-defined]
        for label, uri, kind in self._rows:
            score = matcher.match(label)
            if score > 0:
                display = f"{data.ICON.get(kind, '')} {label}"
                yield Hit(
                    score, matcher.highlight(display), partial(jump, uri), text=label, help=kind
                )
