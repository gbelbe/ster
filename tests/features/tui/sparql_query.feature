Feature: SPARQL query workspace in the New-TUI
  As an ontology author
  I want to run SPARQL against the open ontology without leaving the browser
  So that I can inspect and check it interactively

  Background:
    Given the New-TUI is open on the demo ontology

  Scenario: Open the query screen from the browser
    When I open the query screen
    Then the SPARQL editor is shown

  Scenario: Run a SELECT query against the live ontology
    When I open the query screen
    And I run the query "SELECT ?c WHERE { ?c a <http://www.w3.org/2002/07/owl#Class> }"
    Then the results table has more than one row

  Scenario: A malformed query reports an error instead of crashing
    When I open the query screen
    And I run the query "SELECT ?s WHERE { this is not sparql"
    Then an error is reported and the results are empty

  Scenario: Load a preset into the editor
    When I open the query screen
    And I load the first preset
    Then the editor contains the preset query

  Scenario: Close the query screen returns to the browser
    When I open the query screen
    And I close the query screen
    Then the browser tree is shown again
