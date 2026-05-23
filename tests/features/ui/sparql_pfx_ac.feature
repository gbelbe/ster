Feature: SPARQL prefix name autocomplete

  Background:
    Given a known prefix set containing "kai", "skos", "owl", "rdf"

  Scenario: empty filter returns all prefixes sorted alphabetically
    When prefix candidates are requested with filter ""
    Then the result is ["kai", "owl", "rdf", "skos"]

  Scenario: filter restricts to matching prefixes
    When prefix candidates are requested with filter "s"
    Then the result is ["skos"]

  Scenario: filter is case-insensitive
    When prefix candidates are requested with filter "SK"
    Then the result is ["skos"]

  Scenario: no match returns empty list
    When prefix candidates are requested with filter "xyz"
    Then the result is []

  Scenario: multiple prefixes share a common start
    Given a known prefix set containing "rdf", "rdfs", "rdfa"
    When prefix candidates are requested with filter "rdf"
    Then the result is ["rdf", "rdfa", "rdfs"]

  Scenario: exact match is included
    When prefix candidates are requested with filter "owl"
    Then the result is ["owl"]
