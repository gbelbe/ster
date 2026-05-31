Feature: Graph node search

  Background:
    Given a taxonomy with OWL classes "Animal" and "Dog"

  Scenario: Search input is present in full graph view
    When I render the full VOWL graph HTML
    Then the HTML contains a search input element

  Scenario: Search input is present in focused graph view
    When I render a focused VOWL graph HTML rooted at "Animal"
    Then the HTML contains a search input element

  Scenario: Search input is present in query result view
    When I render the query result VOWL graph HTML for "Animal"
    Then the HTML contains a search input element

  Scenario: searchNodes JavaScript function is included
    When I render the full VOWL graph HTML
    Then the HTML contains the searchNodes JavaScript function

  Scenario: clearSearch is wired to the Escape key
    When I render the full VOWL graph HTML
    Then the HTML contains clearSearch called on the Escape key
