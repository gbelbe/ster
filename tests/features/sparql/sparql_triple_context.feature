Feature: SPARQL triple-position-aware autocomplete context

  Scenario: Subject position returns any context
    Given a SPARQL buffer "WHERE { kai:"
    When _sparql_context_at_cursor is called at end of buffer
    Then the context is "any"

  Scenario: Predicate position returns property context
    Given a SPARQL buffer "WHERE { kai:Foo kai:"
    When _sparql_context_at_cursor is called at end of buffer
    Then the context is "property"

  Scenario: Object position after unknown predicate returns any context
    Given a SPARQL buffer "WHERE { kai:Foo kai:bar kai:"
    When _sparql_context_at_cursor is called at end of buffer
    Then the context is "any"

  Scenario: After dot separator position two is predicate
    Given a SPARQL buffer "WHERE { kai:A kai:p kai:B . kai:C kai:"
    When _sparql_context_at_cursor is called at end of buffer
    Then the context is "property"

  Scenario: After semicolon the next token is predicate
    Given a SPARQL buffer "WHERE { kai:A kai:p kai:B ; kai:"
    When _sparql_context_at_cursor is called at end of buffer
    Then the context is "property"

  Scenario: Class predicate object still returns class context
    Given a SPARQL buffer "WHERE { ?x rdf:type kai:"
    When _sparql_context_at_cursor is called at end of buffer
    Then the context is "class"
