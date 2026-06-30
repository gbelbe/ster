Feature: Configured languages drive label editing and deletion
  The configured languages decide which "+ Add label" rows appear, and removing a
  language can purge all of its labels/descriptions from the file.

  Scenario: Adding a configured language reveals its add-label row
    Given the zoo ontology is open with configured languages "en"
    When I select a class and configure languages "en, fr"
    Then a "+ Add rdfs:label [fr]" row is offered

  Scenario: Removing a language with data offers to delete it
    Given the zoo ontology is open with configured languages "en, fr"
    And a class has a French label
    When I unconfigure language "fr" and choose to delete its data
    Then no French label remains in the ontology

  Scenario: Removing a language but keeping its data
    Given the zoo ontology is open with configured languages "en, fr"
    And a class has a French label
    When I unconfigure language "fr" and choose to keep its data
    Then the French label still exists in the ontology
