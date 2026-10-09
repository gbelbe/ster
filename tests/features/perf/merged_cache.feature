Feature: Reopening a heavy project from a saved graph
  The first open of a project with many context files is slow. ster saves the
  merged graph so later opens are fast, until a file changes.

  Scenario: Reopening an unchanged project
    Given a project with context files that was opened once
    When the project is opened again
    Then the saved graph is loaded and no file is parsed

  Scenario: A file was edited
    Given a project with context files that was opened once
    When a context file is edited
    Then the project is rebuilt from the files

  Scenario: A file is replaced by older content
    Given a project with context files that was opened once
    When a context file is replaced by different content with an older timestamp
    Then the project is rebuilt from the files

  Scenario: A file was touched but not changed
    Given a project with context files that was opened once
    When a context file is touched without changing it
    Then the saved graph is loaded and no file is parsed

  Scenario: The saved graph is damaged
    Given a project with context files that was opened once
    When the saved graph is corrupted
    Then the project is rebuilt from the files

  Scenario: Clearing the saved graphs
    Given a project with context files that was opened once
    When the user clears the cache
    Then the saved graphs are deleted and downloaded assets are kept
    And the next open rebuilds from the files
