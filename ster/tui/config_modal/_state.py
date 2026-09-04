"""Static-typing surface shared by every ``ConfigModal`` mixin: declares every
attribute and method ``ConfigModal`` (see ``__init__.py``) ends up with, so mypy
can check cross-mixin ``self.foo()`` calls inside one mixin's methods even though
that mixin doesn't itself define ``foo`` — some sibling mixin does, once they're
all composed into the real ``ConfigModal`` class.

This is a typing-only construct, generated from (and kept behaviour-identical to)
the original monolithic class's signatures and instance attributes. The
``TYPE_CHECKING`` branch is what mypy sees; the runtime branch is a bare, empty
class that changes nothing about any mixin's actual behaviour or MRO. Attributes
``ModalBase``/``Widget`` already provide (``query_one``, ``query``, ``app``,
``screen``, ``post_message``, ``focused``, …) are intentionally left out — they
come free from the base classes below.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ster.metadata_coverage import MetaProp

    from ..modal import ModalBase
    from ._metadata_catalog import _MetaCatalog

    class _ModalState(ModalBase[None]):
        """Every attribute/method a mixin may borrow from a sibling mixin, for
        mypy only — never instantiated, never a real base at runtime."""

        # message classes declared on ConfigModal itself (kept as Any: each has
        # its own constructor signature, not the plain zero-arg Message base)
        Changed: Any
        WriteOntoCi: Any

        # set in ConfigModal.__init__
        _display: str
        _available: list[str]
        _themes: list[str]
        _theme: str
        _configured: list[str]
        _metadata: list[MetaProp]
        _entity_metadata: list[MetaProp]
        _annotation_verifier: Callable[[str], bool] | None
        _can_declare: bool
        _base_uri: str
        _server_url: str
        _server_port: int
        _server_token: str
        _ready: bool

        # compose helpers, one per tab (each mixin defines its own)
        def _general_tab(self) -> Any: ...
        def _props_tab(self) -> Any: ...
        def _plugins_tab(self) -> Any: ...
        def _semanticlint_widgets(self) -> Any: ...

        # auto-save / result (state mixin)
        def _result(self) -> dict: ...
        def _semanticlint_result(self) -> dict: ...
        def _csv(self, selector: str) -> list[str]: ...
        def _save(self) -> None: ...

        # metadata catalogs (props mixin)
        def _on_catalog_changed(self, event: _MetaCatalog.Changed) -> None: ...

        # languages (general mixin)
        async def _add_typed_languages(self) -> None: ...

        # navigation (navigation mixin)
        def _tab_ids(self) -> list[str]: ...
        @staticmethod
        def _focus_catalog(catalog: _MetaCatalog) -> None: ...

else:

    class _ModalState:
        """Runtime no-op base — real behaviour comes only from the mixins that
        are actually composed into ``ConfigModal``."""
