Feature: Editing one file against read-only context

  A taxonomy is often split across files, but ster loads one at a time — so the
  graph on screen is never the graph you actually have. Loading the others as
  read-only context shows the whole connected graph while keeping exactly one
  file writable.

  Which file an entity came from therefore becomes part of what the interface
  has to say: an entity you cannot edit must look different from one you can,
  and saving must never absorb a context file into the editable one.

  Background:
    Given a gear file defining "Tent"
    And a places file defining "Alps"

  Scenario: The whole graph is visible
    When both files are loaded with the gear file editable
    Then both "Tent" and "Alps" are in the taxonomy

  Scenario: Only the editable file's entities can be edited
    When both files are loaded with the gear file editable
    Then "Tent" is editable
    And "Alps" is read-only

  Scenario: A read-only entity says where it came from
    When both files are loaded with the gear file editable
    Then "Alps" reports the places file as its source

  Scenario: Saving never absorbs the context file
    When both files are loaded with the gear file editable
    And the taxonomy is saved
    Then the gear file still defines "Tent"
    And the gear file does not define "Alps"

  Scenario: Saving leaves the context file untouched
    When both files are loaded with the gear file editable
    And the taxonomy is saved
    Then the places file is unchanged

  Scenario: Loading a single file leaves everything editable
    When only the gear file is loaded
    Then "Tent" is editable
    And nothing is read-only
