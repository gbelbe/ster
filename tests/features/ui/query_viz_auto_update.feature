Feature: Auto-update WebVOWL window after SPARQL query execution

  Scenario: query result HTML contains a Show all nodes button when link provided
    Given a valid taxonomy with a matching URI
    When the query result HTML is built with a full_graph_link
    Then the rendered HTML contains a Show all nodes button

  Scenario: query result HTML has no Show all nodes button without link
    Given a valid taxonomy with a matching URI
    When the query result HTML is built without a full_graph_link
    Then the rendered HTML does not contain a Show all nodes button

  Scenario: full ontology HTML never contains a Show all nodes button
    Given a valid taxonomy with a matching URI
    When render_vowl_html is called
    Then the rendered HTML does not contain a Show all nodes button

  Scenario: open_query_result_in_browser writes the full graph file
    Given a valid taxonomy with a matching URI and a file path
    When open_query_result_in_browser is called
    Then a full graph HTML file is written alongside the query result file
