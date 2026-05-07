Feature: Visual distinction for external ontology terms
  As a user browsing an ontology that references external namespaces
  I want external classes, properties and individuals to be visually distinct
  So that I can immediately tell what belongs to my ontology vs. what is imported

  Background:
    Given a taxonomy with local class "kai:Person" and external "foaf:Person" in namespace_bindings

  Scenario: External URI identified correctly
    When I call is_external_uri for "foaf:Person"
    Then the result is True

  Scenario: Local URI is not external
    When I call is_external_uri for "kai:Person"
    Then the result is False

  Scenario: Built-in OWL URI is not external
    When I call is_external_uri for "owl:Class"
    Then the result is False

  Scenario: Prefix label for known namespace
    When I call prefix_label for "foaf:Person"
    Then the label is "foaf:Person"

  Scenario: Prefix label falls back to local name for unknown namespace
    Given a taxonomy with no namespace bindings
    When I call prefix_label for "http://unknown.org/ns#Thing"
    Then the label is "Thing"

  Scenario: GraphViz marks external class with external-class type
    Given a taxonomy where "foaf:Person" is in owl_classes and namespace_bindings
    When I call build_graph
    Then the node for "foaf:Person" has type "external-class"

  Scenario: GraphViz marks local class with class type
    When I call build_graph
    Then the node for "kai:Person" has type "class"
