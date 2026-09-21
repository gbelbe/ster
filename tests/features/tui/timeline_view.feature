Feature: Opening the timeline view from the ontology

  A shortcut in the ontology view opens a frieze of everything in the file that
  carries a date — concepts, classes or individuals alike, since the timeline
  keys off temporal literal datatypes rather than the kind of entity.

  A file holding none gets a warning instead of a window, for the reason the
  map gives: an empty frieze is not an answer, and the reader cannot tell it
  from one that failed to load.

  Scenario: The shortcut opens the frieze of everything with a date
    Given the ster server is running
    And the file carries dates
    When the timeline shortcut is pressed in the ontology view
    Then a browser is opened on the timeline page

  Scenario: A file with no dates is refused rather than shown empty
    Given the ster server is running
    And the file carries no dates at all
    When the timeline shortcut is pressed in the ontology view
    Then no browser is opened for the timeline
    And the TUI reports that nothing can be dated

  Scenario: The TUI says so when the server is not running
    Given the ster server is not running
    And the file carries dates
    When the timeline shortcut is pressed in the ontology view
    Then no browser is opened for the timeline
    And the TUI reports that the timeline server is not running
