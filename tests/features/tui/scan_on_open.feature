Feature: Scan the ontology for errors when it opens
  As an ontology editor
  I want blocking errors surfaced in a fix-it worklist the moment I open a file
  So that I can resolve them in place, without hunting through the tree

  Background:
    Given the semanticlint plugin is enabled

  Scenario: A file with a blocking error opens the Problems worklist
    Given an ontology file that has a duplicate-label error
    When I open it in the TUI
    Then the Problems modal lists 1 error

  Scenario: A clean file opens without interruption
    Given an ontology file with no blocking errors
    When I open it in the TUI
    Then no Problems modal appears

  Scenario: An inline auto-fix resolves the error and closes the worklist
    Given an ontology file that has a duplicate-label error
    And I have opened it in the TUI
    When I apply the inline fix
    Then the duplicate label is removed
    And the Problems modal closes

  Scenario: The scan is skipped when "check file on open" is off
    Given "check file on open" is turned off
    And an ontology file that has a duplicate-label error
    When I open it in the TUI
    Then no Problems modal appears
