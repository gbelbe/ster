Feature: Renaming any entity URI reports the number of affected statements

  A URI rename is a cross-cutting edit: the same generic flow (detect the layer,
  count the affected statements, rename, propagate) applies whether the URI
  denotes a SKOS concept, an OWL entity, or a node promoted to both. The common
  front (rename_kind / count_uri_references / rename_entity_uri) hides the
  SKOS-vs-OWL specifics from callers.

  Scenario: Renaming a concept URI reports the number of affected statements
    Given a model with concept "Animal" and concept "Dog" broader "Animal"
    When I ask for the rename kind of "Animal"
    Then the rename kind is "concept"
    And counting all references to "Animal" returns at least 2

  Scenario: Renaming a class URI reports the number of affected statements
    Given a model with class "Animal" and class "Dog" subClassOf "Animal"
    When I ask for the rename kind of "Animal"
    Then the rename kind is "class"
    And counting all references to "Animal" returns at least 2

  Scenario: Renaming a promoted concept/class counts statements in both layers
    Given a model with concept "Animal" and concept "Dog" broader "Animal"
    And "Animal" is also an OWL class with subclass "Pet"
    When I ask for the rename kind of "Animal"
    Then the rename kind is "promoted"
    And counting all references to "Animal" is at least the concept plus class counts

  Scenario: Renaming via the common front propagates a concept across mapping properties
    Given a model with concept "Cat" and concept "Dog" exactMatch "Cat"
    When I rename entity "Cat" to "Feline"
    Then concept "Feline" exists in the model
    And concept "Cat" does not exist in the model
    And "Dog" exactMatch contains "Feline"

  Scenario: Renaming a promoted node via the common front updates both layers
    Given a model with concept "Animal" and concept "Dog" broader "Animal"
    And "Animal" is also an OWL class with subclass "Pet"
    When I rename entity "Animal" to "Creature"
    Then concept "Creature" exists in the model
    And class "Creature" exists in the model
    And "Dog" broader contains "Creature"
    And "Pet" subClassOf contains "Creature"
