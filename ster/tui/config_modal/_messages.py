"""Messages posted by the config modal's metadata catalog for the app to act on."""

from __future__ import annotations

from textual.message import Message


class DeclareAnnotationProperty(Message):
    """Ask the app to declare *uri* as a local ``owl:AnnotationProperty``.

    Posted when the user confirms keeping a predicate that is not (yet) a known
    annotation property, or creates a brand-new local one from the config modal.
    The app runs the OWL command(s) — writing *label* / *comment* when given —
    and saves to the open ``.ttl``.
    """

    def __init__(self, uri: str, label: str = "", comment: str = "") -> None:
        super().__init__()
        self.uri = uri
        self.label = label
        self.comment = comment


class EnforceShaclRequested(Message):
    """Ask the app to write (or remove) a mandatory SHACL rule for an annotation
    property configured in a catalog.

    *scope* is ``"ontology"`` (require it on the ontology node) or ``"entity"``
    (require it on every owl:Class and skos:Concept). *enforce* True writes the
    rule, False removes it. The app owns the ontology file, so it does the I/O.
    """

    def __init__(self, predicate: str, label: str, enforce: bool, scope: str) -> None:
        super().__init__()
        self.predicate = predicate
        self.label = label
        self.enforce = enforce
        self.scope = scope
