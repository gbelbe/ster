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

  # Phase 4 — SKOS concepts

  Scenario: Set a concept prefLabel
    Given a SKOS taxonomy is open for editing
    When I set the prefLabel of the concept "Top" to "Apex"
    Then the concept "Top" has prefLabel "Apex"

  Scenario: Set a concept definition
    Given a SKOS taxonomy is open for editing
    When I set the definition of the concept "Top" to "The root concept."
    Then the concept "Top" has definition "The root concept."

  Scenario: Add a narrower concept
    Given a SKOS taxonomy is open for editing
    When I add a narrower concept "Leaf" under the concept "Top"
    Then the concept "Leaf" exists

  Scenario: Relate two concepts
    Given a SKOS taxonomy is open for editing
    When I relate the concept "Top" to the concept "Sibling"
    Then the concept "Top" is related to "Sibling"

  Scenario: Delete a concept
    Given a SKOS taxonomy is open for editing
    When I delete the concept "Child" choosing "keep"
    Then the concept "Child" no longer exists

  # Phase 5 — SKOS concept schemes

  Scenario: Set the scheme title
    Given a SKOS taxonomy is open for editing
    When I set the title of the scheme to "Catalogue"
    Then the scheme has title "Catalogue"

  Scenario: Add a top concept to the scheme
    Given a SKOS taxonomy is open for editing
    When I add a top concept "Brand" to the scheme
    Then the concept "Brand" exists
