Feature: Offering a map for query results that carry geodata

  Running a SPARQL query in the TUI should point out when its results can be
  put on a map, without interrupting the edit-and-rerun loop.

  Scenario: The status line offers the map when results carry coordinates
    Given a taxonomy whose individuals carry WGS84 coordinates
    When a query returning those individuals is run in the query screen
    Then the status line reports how many rows can be mapped
    And the status line mentions the map shortcut

  Scenario: The status line stays quiet when results carry none
    Given a taxonomy whose individuals carry WGS84 coordinates
    When a query returning no coordinates is run in the query screen
    Then the status line does not mention the map shortcut

  Scenario: Opening the map hands the current query to the browser
    Given a taxonomy whose individuals carry WGS84 coordinates
    When a query returning those individuals is run in the query screen
    And the map shortcut is pressed
    Then a browser is opened on the map page
    And the opened address carries the query

  Scenario: The TUI says so when the server is not running
    Given a taxonomy whose individuals carry WGS84 coordinates
    And the ster server is not running
    When a query returning those individuals is run in the query screen
    And the map shortcut is pressed
    Then no browser is opened
    And the TUI reports that the server is not running
