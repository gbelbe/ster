Feature: Changing which file is the working file

  Loading a taxonomy against read-only context gives the whole connected graph
  with exactly one file writable — but which one that is was decided when the
  session opened. Editing something in another file meant quitting and
  reopening, which is why the interface could only ever say "Open that file to
  edit it".

  Changing the working file mid-session swaps the roles instead: the chosen
  file becomes the one writable file and the previous one joins the context.
  The same files stay loaded, so the graph on screen never shrinks — only the
  answer to "what may I edit?" changes, and it has to change everywhere at
  once, for the editor and for the API serving the same session.

  Background:
    Given a gear file defining "Tent"
    And a places file defining "Alps"
    And both files are open with the gear file as the working file

  Scenario: The chosen file becomes writable
    When the places file is made the working file
    Then "Alps" is editable

  Scenario: The previous working file becomes context
    When the places file is made the working file
    Then "Tent" is read-only
    And "Tent" reports the gear file as its source

  Scenario: The whole graph survives the switch
    When the places file is made the working file
    Then both "Tent" and "Alps" are in the taxonomy

  Scenario: Edits after a switch land in the newly chosen file
    When the places file is made the working file
    And "Alps" is relabelled "Alpes"
    And the taxonomy is saved
    Then the places file defines "Alpes"
    And the gear file is unchanged

  Scenario: An unsaved edit is written before the switch, to its own file
    Given "Tent" has been relabelled "Tente" without saving yet
    When the places file is made the working file
    Then the gear file defines "Tente"
    And the places file does not define "Tente"

  Scenario: Switching to the file that is already writable changes nothing
    When the gear file is made the working file
    Then the taxonomy is not reloaded
    And "Tent" is editable

  Scenario: The API agrees about what may be edited
    When the places file is made the working file
    Then the API refuses to write to "Tent"
    And the API accepts a write to "Alps"

  Scenario: The API writes to the new working file
    When the places file is made the working file
    And the API renames "Alps" to "Alpes"
    Then the places file defines "Alpes"
    And the gear file is unchanged

  Scenario: A file that has vanished cannot be made the working file
    Given the places file has been deleted from disk
    When the places file is made the working file
    Then the switch is refused with a message naming the places file
    And "Tent" is still editable
