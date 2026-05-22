Feature: Visualize SPARQL query results in the graph view

  # ── open_query_result_in_browser ─────────────────────────────────────────────

  Scenario: Visualizing results with matched URIs opens the browser
    Given a taxonomy containing concepts A and B
    And a query result whose rows contain the URIs of A and B
    When I open query result viz
    Then the browser is opened
    And the opened URL is non-empty

  Scenario: Visualizing results with no URI values raises an error
    Given a taxonomy containing concept A
    And a query result containing only literal values
    When I open query result viz
    Then a ValueError is raised indicating no matching nodes

  Scenario: Visualizing an empty result set raises an error
    Given a taxonomy containing concept A
    And a query result with no rows
    When I open query result viz
    Then a ValueError is raised indicating no matching nodes
