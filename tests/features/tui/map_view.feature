Feature: Opening the map view from the ontology

  A shortcut in the ontology view opens the map of everything in the file that
  carries geography — concepts, classes or individuals alike, since the map
  keys off WGS84 coordinates and GeoSPARQL shapes rather than the kind of
  entity.

  A file holding neither gets a warning instead of a window. An empty map is
  not an answer: the reader cannot tell it from one that failed to load.

  Scenario: The shortcut opens the map of everything with coordinates
    Given the ster server is running
    And the file carries coordinates
    When the map shortcut is pressed in the ontology view
    Then a browser is opened on the map page

  Scenario: A file with no geography is refused rather than shown empty
    Given the ster server is running
    And the file carries no geography at all
    When the map shortcut is pressed in the ontology view
    Then no browser is opened
    And the TUI reports that nothing can be mapped

  Scenario: The TUI says so when the server is not running
    Given the ster server is not running
    And the file carries coordinates
    When the map shortcut is pressed in the ontology view
    Then no browser is opened
    And the TUI reports that the server is not running
