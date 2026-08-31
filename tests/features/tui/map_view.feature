Feature: Opening the map view from the ontology

  A shortcut in the ontology view opens the map of everything in the file that
  carries coordinates — concepts, classes or individuals alike, since the map
  keys off WGS84 data rather than the kind of entity.

  Scenario: The shortcut opens the map of everything with coordinates
    Given the ster server is running
    When the map shortcut is pressed in the ontology view
    Then a browser is opened on the map page

  Scenario: The TUI says so when the server is not running
    Given the ster server is not running
    When the map shortcut is pressed in the ontology view
    Then no browser is opened
    And the TUI reports that the server is not running
