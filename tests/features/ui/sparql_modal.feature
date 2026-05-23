Feature: SPARQL query modal over tree view

  Scenario: SPARQL modal opens from tree view with S key
    Given the viewer is in tree view mode
    When the user presses "S"
    Then the viewer switches to query state

  Scenario: SPARQL modal closes with Esc and returns to tree
    Given the viewer is in query state
    When the user presses Esc in the query editor
    Then the viewer returns to tree view mode

  Scenario: Running a query auto-refreshes an already-open viz window
    Given a viz file has been written to disk at a known path
    And a new query produces result URIs that match taxonomy nodes
    When the query completes successfully
    Then the viz HTML file is overwritten with updated content

  Scenario: Running a query does not open viz automatically when none is open
    Given no viz file path is tracked
    And a query produces result URIs that match taxonomy nodes
    When the query completes successfully
    Then no viz file is written
