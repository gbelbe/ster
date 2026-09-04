Feature: Taxonomy treemap tab in the graph view

  Scenario: Opening a SKOS-only taxonomy shows the Taxonomie tab by default
    Given a SKOS-only taxonomy
    When the graph view HTML is rendered
    Then the rendered HTML carries a taxonomy payload
    And the tab bar markup is present

  Scenario: Opening a mixed SKOS and OWL taxonomy shows both tabs
    Given a mixed SKOS and OWL taxonomy
    When the graph view HTML is rendered
    Then the rendered HTML carries a taxonomy payload
    And the rendered HTML carries OWL class nodes

  Scenario: Opening an OWL-only taxonomy shows no taxonomy tab
    Given an OWL-only taxonomy
    When the graph view HTML is rendered
    Then the rendered HTML carries no taxonomy payload
    And the rendered HTML carries OWL class nodes

  Scenario: Selecting a concept tile can show its detail in the panel
    Given a SKOS-only taxonomy
    When the concept detail map is built
    Then the concept's detail is available for the panel
