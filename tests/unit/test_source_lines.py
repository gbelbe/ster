"""Where a subject starts a statement in its file — the line the source pane shows.

rdflib keeps no line numbers, so the file's text is read again. Only the first
line of a statement matters: that is where the reader goes to find it. When a
line cannot be placed with certainty, nothing is returned — a missing number
costs a search, a wrong one sends the reader to the wrong place.
"""

from __future__ import annotations

from ster.source_lines import SourceLines

EX = "https://example.org/s#"
_HEAD = f"@prefix ex: <{EX}> .\n@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"


def _lines(tmp_path, body: str, name: str = "f.ttl", head: str = _HEAD) -> SourceLines:
    path = tmp_path / name
    path.write_text(head + body, encoding="utf-8")
    found = SourceLines.from_file(path)
    assert found is not None
    return found


def test_a_subject_at_the_start_of_a_line_is_found(tmp_path) -> None:
    lines = _lines(tmp_path, "\nex:A a skos:Concept .\n")
    assert lines.starts(EX + "A") == [4]


def test_a_statement_continued_over_several_lines_gives_its_first_line(tmp_path) -> None:
    lines = _lines(
        tmp_path, 'ex:A a skos:Concept ;\n    skos:prefLabel "A"@en ;\n    skos:notation "1" .\n'
    )
    assert lines.starts(EX + "A") == [3]


def test_the_file_s_own_prefix_name_is_what_counts(tmp_path) -> None:
    head = f"@prefix mine: <{EX}> .\n"
    lines = _lines(
        tmp_path, "mine:A a <http://www.w3.org/2004/02/skos/core#Concept> .\n", head=head
    )
    assert lines.starts(EX + "A") == [2]


def test_a_full_iri_subject_is_found(tmp_path) -> None:
    lines = _lines(tmp_path, f"<{EX}A> a skos:Concept .\n")
    assert lines.starts(EX + "A") == [3]


def test_sparql_style_prefix_declarations_are_read(tmp_path) -> None:
    head = f"PREFIX ex: <{EX}>\n"
    lines = _lines(tmp_path, "ex:A ex:p ex:B .\n", head=head)
    assert lines.starts(EX + "A") == [2]


def test_a_subject_seen_only_as_an_object_is_not_a_start(tmp_path) -> None:
    lines = _lines(tmp_path, "ex:B skos:broader\n    ex:A .\n")
    assert lines.starts(EX + "A") == []


def test_a_line_inside_a_multiline_string_is_not_a_start(tmp_path) -> None:
    body = (
        'ex:B skos:definition """first\nex:A a skos:Concept .\nlast""" .\nex:A a skos:Concept .\n'
    )
    lines = _lines(tmp_path, body)
    assert lines.starts(EX + "A") == [6]


def test_a_commented_out_line_is_not_a_start(tmp_path) -> None:
    lines = _lines(tmp_path, "# ex:A a skos:Concept .\nex:A a skos:Concept .\n")
    assert lines.starts(EX + "A") == [4]


def test_a_hash_inside_an_iri_is_not_a_comment(tmp_path) -> None:
    """The previous statement ends in `.` after an IRI holding `#` — still an end."""
    body = f"ex:B ex:p <{EX}X> .\nex:A a skos:Concept .\n"
    lines = _lines(tmp_path, body)
    assert lines.starts(EX + "A") == [4]


def test_every_statement_a_subject_starts_is_listed(tmp_path) -> None:
    body = 'ex:A a skos:Concept .\nex:B a skos:Concept .\nex:A skos:prefLabel "A" .\n'
    lines = _lines(tmp_path, body)
    assert lines.starts(EX + "A") == [3, 5]


def test_statements_inside_a_trig_graph_are_found(tmp_path) -> None:
    body = "ex:g {\n    ex:A a skos:Concept .\n}\n"
    lines = _lines(tmp_path, body, name="f.trig")
    assert lines.starts(EX + "A") == [4]
    assert lines.starts(EX + "g") == [], "a graph name is not a statement"


def test_n_triples_lines_are_found(tmp_path) -> None:
    body = f"<{EX}B> <{EX}p> <{EX}A> .\n<{EX}A> <{EX}p> <{EX}B> .\n"
    lines = _lines(tmp_path, body, name="f.nt", head="")
    assert lines.starts(EX + "A") == [2]


def test_an_unknown_subject_has_no_lines(tmp_path) -> None:
    assert _lines(tmp_path, "ex:A a skos:Concept .\n").starts(EX + "Nowhere") == []


def test_a_format_without_lines_to_read_gives_nothing(tmp_path) -> None:
    path = tmp_path / "f.rdf"
    path.write_text("<rdf:RDF/>", encoding="utf-8")
    assert SourceLines.from_file(path) is None


def test_an_unreadable_file_gives_nothing(tmp_path) -> None:
    assert SourceLines.from_file(tmp_path / "missing.ttl") is None
