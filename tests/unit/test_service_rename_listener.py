"""TaxonomyService tells listeners which URIs a committed command renamed.

The graph layout is keyed by URI, so a rename would otherwise leave a node's
remembered position under a URI that no longer exists. The service stays free
of any file access: it only reports ``old → new``; the graph server and the TUI
connect that to the layout store.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ster.core.commands import (
    OntoRenameUri,
    OwlMoveClass,
    OwlSaveClass,
    OwlSaveProperty,
    RenameEntity,
)
from ster.core.service import TaxonomyService
from ster.model import OWLProperty, RDFClass, Taxonomy

NS = "https://ex.org/t/"
PATH = Path("/tmp/onto.ttl")


@dataclass
class _Workspace:
    taxonomies: dict[Path, Taxonomy] = field(default_factory=dict)


class _Persistence:
    def save(self, taxonomy: Taxonomy, path: Path) -> None:
        pass


def _taxonomy() -> Taxonomy:
    t = Taxonomy()
    t.ontology_uri = "https://ex.org/t"
    for name in ("Animal", "Dog"):
        t.owl_classes[NS + name] = RDFClass(uri=NS + name)
    t.owl_properties[NS + "eats"] = OWLProperty(uri=NS + "eats", prop_type="ObjectProperty")
    t.owl_classes["https://elsewhere.org/Thing"] = RDFClass(uri="https://elsewhere.org/Thing")
    return t


def _service():
    heard: list[tuple[Path, dict[str, str]]] = []
    service = TaxonomyService(_Workspace({PATH: _taxonomy()}), _Persistence())
    service.add_rename_listener(lambda path, renamed: heard.append((path, renamed)))
    return service, heard


def test_renaming_an_entity_is_reported() -> None:
    service, heard = _service()
    service.execute(RenameEntity(PATH, NS + "Dog", NS + "Hound"))
    assert heard == [(PATH, {NS + "Dog": NS + "Hound"})]


def test_saving_a_class_under_a_new_uri_is_reported() -> None:
    service, heard = _service()
    service.execute(OwlSaveClass(PATH, NS + "Dog", NS + "Hound"))
    assert heard == [(PATH, {NS + "Dog": NS + "Hound"})]


def test_saving_a_class_under_its_own_uri_is_not_a_rename() -> None:
    service, heard = _service()
    service.execute(OwlSaveClass(PATH, NS + "Dog", NS + "Dog"))
    assert heard == []


def test_saving_a_property_under_a_new_uri_is_reported() -> None:
    service, heard = _service()
    service.execute(OwlSaveProperty(PATH, NS + "eats", NS + "feedsOn"))
    assert heard == [(PATH, {NS + "eats": NS + "feedsOn"})]


def test_renaming_the_ontology_reports_every_local_entity_and_no_external_one() -> None:
    service, heard = _service()
    service.execute(OntoRenameUri(PATH, "https://ex.org/zoo", "/"))
    [(path, renamed)] = heard
    assert renamed == {
        NS + "Animal": "https://ex.org/zoo/Animal",
        NS + "Dog": "https://ex.org/zoo/Dog",
        NS + "eats": "https://ex.org/zoo/eats",
    }


def test_a_command_that_renames_nothing_reports_nothing() -> None:
    service, heard = _service()
    service.execute(OwlMoveClass(PATH, NS + "Dog", NS + "Animal"))
    assert heard == []


def test_a_failed_rename_reports_nothing() -> None:
    service, heard = _service()
    result = service.execute(RenameEntity(PATH, NS + "Dog", NS + "Animal"))  # URI taken
    assert result.status == "failed"
    assert heard == []
