Feature: Native RDF parsing for large files

  Opening a large ontology spends most of its time in rdflib's Python parser.
  pyoxigraph parses the same bytes in Rust — measured 7.4x faster on N-Triples
  and 15.9x on RDF/XML — so ster uses it to build the taxonomy and keeps rdflib
  as the fallback for anything it cannot parse.

  The result must be indistinguishable from the rdflib path: same entities, same
  hierarchy, and the same namespace bindings, including the prefix rdflib renames
  when a file re-uses one of its built-in prefix names for a different namespace.

  Scenario: A Turtle taxonomy loads identically through the native parser
    Given a Turtle taxonomy file
    When ster loads it
    Then the taxonomy has the same entities as the rdflib parser produces
    And the namespace bindings match the rdflib parser exactly

  Scenario: An RDF/XML ontology loads identically through the native parser
    Given an RDF/XML ontology file
    When ster loads it
    Then the taxonomy has the same entities as the rdflib parser produces
    And the namespace bindings match the rdflib parser exactly

  Scenario: A file re-using a built-in prefix name keeps rdflib's disambiguation
    Given a Turtle file binding "geo" to a namespace rdflib reserves for another
    When ster loads it
    Then the namespace bindings match the rdflib parser exactly

  Scenario: A format the native parser cannot handle still loads
    Given a JSON-LD taxonomy file
    When ster loads it
    Then the taxonomy has the same entities as the rdflib parser produces

  Scenario: A malformed file still reports its syntax error
    Given a malformed Turtle file
    When ster loads it
    Then the load fails with a syntax error
