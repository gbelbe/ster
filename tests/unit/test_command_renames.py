"""What a command renamed, asked the way each kind of command can answer.

Two protocols rather than one: a single-entity rename knows its own old and new
URI, while a namespace change can only list what it moved by reading the model
it was applied to. Giving every command that model (SonarQube S1172 on #252)
left three of them with a parameter they never used.
"""

from __future__ import annotations

from pathlib import Path

from ster.core.commands.base import ChangeSet, Renames, RenamesInModel, renames_of
from ster.core.commands.cross import RenameEntity
from ster.core.commands.onto import OntoRenameUri
from ster.model import RDFClass, Taxonomy

PATH = Path("o.ttl")
NS = "https://example.org/zoo#"


def _zoo() -> Taxonomy:
    tax = Taxonomy()
    tax.ontology_uri = "https://example.org/zoo"
    tax.owl_classes[NS + "Dog"] = RDFClass(uri=NS + "Dog")
    return tax


def test_a_single_entity_rename_answers_without_a_model():
    command = RenameEntity(PATH, NS + "Dog", NS + "Canine")

    assert isinstance(command, Renames)
    assert not isinstance(command, RenamesInModel)
    assert command.renamed_uris() == {NS + "Dog": NS + "Canine"}


def test_renaming_to_the_same_uri_reports_nothing():
    assert RenameEntity(PATH, NS + "Dog", NS + "Dog").renamed_uris() == {}


def test_a_namespace_change_reads_what_moved_from_the_model_before_it():
    command = OntoRenameUri(PATH, "https://example.org/zoo2", "#")

    assert isinstance(command, RenamesInModel)
    assert renames_of(command, _zoo()) == {NS + "Dog": "https://example.org/zoo2#Dog"}


def test_a_batch_reports_every_rename_it_holds():
    batch = ChangeSet(
        PATH,
        (
            RenameEntity(PATH, NS + "Dog", NS + "Canine"),
            RenameEntity(PATH, NS + "Cat", NS + "Feline"),
        ),
    )

    assert renames_of(batch, _zoo()) == {NS + "Dog": NS + "Canine", NS + "Cat": NS + "Feline"}


def test_a_batch_holding_a_namespace_change_reads_the_model_for_it():
    batch = ChangeSet(PATH, (OntoRenameUri(PATH, "https://example.org/zoo2", "#"),))

    assert isinstance(batch, RenamesInModel)
    assert renames_of(batch, _zoo()) == {NS + "Dog": "https://example.org/zoo2#Dog"}


def test_a_command_that_cannot_rename_reports_nothing():
    assert renames_of(object(), _zoo()) == {}
