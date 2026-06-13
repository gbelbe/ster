Feature: Editing the ontology in the New-TUI
  As a curator I can create, rename, re-link and delete OWL classes and
  individuals from the detail panel. Every change is validated by the core and
  written back to the .ttl, so the file stays consistent.

  # Phase 1 — OWL classes

  Scenario: Rename a class everywhere
    Given the zoo ontology is open for editing
    When I rename the class "Cat" to "Feline"
    Then the class "Feline" exists
    And the class "Cat" no longer exists

  Scenario: Edit a class label
    Given the zoo ontology is open for editing
    When I set the label of the class "Cat" to "Kitty"
    Then the class "Cat" has the label "Kitty"

  Scenario: Add a subclass
    Given the zoo ontology is open for editing
    When I add a subclass "Kitten" under the class "Cat"
    Then the class "Kitten" exists

  Scenario: Add a superclass (polyhierarchy)
    Given the zoo ontology is open for editing
    When I add the superclass "Person" to the class "Cat"
    Then the class "Cat" is a subclass of "Person"

  Scenario: Remove a superclass
    Given the zoo ontology is open for editing
    When I remove the superclass "Mammal" from the class "Cat"
    Then the class "Cat" is not a subclass of "Mammal"

  Scenario: Delete a class
    Given the zoo ontology is open for editing
    When I delete the class "Cat" choosing "delete_all"
    Then the class "Cat" no longer exists

  # Phase 2 — OWL individuals

  Scenario: Create an individual of a class
    Given the zoo ontology is open for editing
    When I add an individual "Mimi" of the class "Cat"
    Then the individual "Mimi" exists

  Scenario: Add a class membership to an individual
    Given the zoo ontology is open for editing
    When I add the type "Cat" to the individual "Rex"
    Then the individual "Rex" has type "Cat"

  Scenario: Remove a class membership from an individual
    Given the zoo ontology is open for editing
    When I remove the type "Dog" from the individual "Rex"
    Then the individual "Rex" does not have type "Dog"

  Scenario: Delete an individual
    Given the zoo ontology is open for editing
    When I delete the individual "Rex"
    Then the individual "Rex" no longer exists

  # Phase 3 — ontology overview (the global window)

  Scenario: Set the ontology title from the overview
    Given the zoo ontology is open for editing
    When I set the ontology title to "Zoo Ontology"
    Then the ontology overview shows "Zoo Ontology"

  Scenario: Set the ontology prefix from the overview
    Given the zoo ontology is open for editing
    When I set the ontology prefix to "zoo"
    Then the saved file declares the prefix "zoo"
