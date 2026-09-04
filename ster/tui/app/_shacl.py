"""Enabling/disabling SHACL constraint enforcement on the loaded taxonomy."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from .. import data
from ._state import _AppState

_LIT_WARNING: Final = "warning"


class _ShaclMixin(_AppState):
    """Mixin: enabling/disabling SHACL constraint enforcement on the loaded taxonomy."""

    def _enforce_shacl(self, prop_uri: str, path: Path) -> None:
        """Write a SHACL rule making *prop_uri* mandatory on each of its domain classes
        into the sibling ``<stem>.shapes.ttl`` (idempotent), then refresh the lint so the
        rule is enforced live. Warns when the property has no domain to attach it to."""
        import datetime

        from ster.plugins.semanticlint import shapes_author as shacl

        prop = self.tax.owl_properties.get(prop_uri)
        if prop is None:
            self.notify("Not an OWL property.", severity=_LIT_WARNING)
            return
        if not prop.domains:
            self.notify(
                "This property has no domain — nothing to make it mandatory on.",
                severity=_LIT_WARNING,
            )
            return
        prop_label = prop.label(self.lang) or prop.local_name
        today = datetime.date.today().isoformat()
        rules = [
            shacl.mandatory_property_rule(
                dom,
                prop_uri,
                target_label=data.label_of(self.tax, dom, self.lang),
                prop_label=prop_label,
                date=today,
            )
            for dom in prop.domains
        ]
        written = shacl.append_rules(shacl.shapes_path_for(path), rules)
        if not written:
            self.notify(f"“{prop_label}” is already enforced.")
            return
        self.notify(f"Enforced “{prop_label}” as mandatory — {len(written)} SHACL rule(s).")
        self._invalidate_lint()
        self._refresh_lint_async()  # the new rule takes effect on the next lint pass

    def _unenforce_shacl(self, prop_uri: str, path: Path) -> None:
        """Remove the SHACL rule(s) that make *prop_uri* mandatory (one per domain) from
        the sibling ``<stem>.shapes.ttl``, then refresh the lint."""
        from ster.plugins.semanticlint import shapes_author as shacl

        prop = self.tax.owl_properties.get(prop_uri)
        if prop is None:
            self.notify("Not an OWL property.", severity=_LIT_WARNING)
            return
        iris = [shacl.shape_iri(dom, prop_uri) for dom in prop.domains]
        removed = shacl.remove_rules(shacl.shapes_path_for(path), iris)
        prop_label = prop.label(self.lang) or prop.local_name
        if not removed:
            self.notify(f"No SHACL rule to remove for “{prop_label}”.")
            return
        self.notify(f"Removed the SHACL rule for “{prop_label}” — {len(removed)} rule(s).")
        self._invalidate_lint()
        self._refresh_lint_async()
