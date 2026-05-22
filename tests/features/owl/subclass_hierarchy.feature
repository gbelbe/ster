Feature: OWL subclass hierarchy management

  Scenario: Add a subclass link between two existing classes
    Given a taxonomy with OWL classes "Animal" and "Dog"
    When I add "Dog" as a subclass of "Animal"
    Then "Dog" has "Animal" in its sub_class_of list

  Scenario: Add a superclass link is the same operation from the parent perspective
    Given a taxonomy with OWL classes "Animal" and "Dog"
    When I add "Animal" as the superclass of "Dog"
    Then "Dog" has "Animal" in its sub_class_of list

  Scenario: Adding the same link twice is idempotent
    Given a taxonomy with OWL classes "Animal" and "Dog"
    When I add "Dog" as a subclass of "Animal"
    And I add "Dog" as a subclass of "Animal" again
    Then "Dog" has exactly one "Animal" entry in its sub_class_of list

  Scenario: Adding a link fails when the child class does not exist
    Given a taxonomy with OWL class "Animal" only
    When I add "Dog" as a subclass of "Animal"
    Then a ClassNotFoundError is raised

  Scenario: Adding a link fails when the parent class does not exist
    Given a taxonomy with OWL class "Dog" only
    When I add "Dog" as a subclass of "Animal"
    Then a ClassNotFoundError is raised

  Scenario: A class cannot be a subclass of itself
    Given a taxonomy with OWL class "Animal" only
    When I add "Animal" as a subclass of "Animal"
    Then a CircularHierarchyError is raised

  Scenario: A direct circular subclass chain is rejected
    Given a taxonomy with OWL classes "Animal" and "Dog"
    And "Dog" is already a subclass of "Animal"
    When I add "Animal" as a subclass of "Dog"
    Then a CircularHierarchyError is raised

  Scenario: An indirect circular subclass chain is rejected
    Given a taxonomy with OWL classes "Animal", "Dog", and "Poodle"
    And "Dog" is already a subclass of "Animal"
    And "Poodle" is already a subclass of "Dog"
    When I add "Animal" as a subclass of "Poodle"
    Then a CircularHierarchyError is raised

  Scenario: A class can have multiple superclasses
    Given a taxonomy with OWL classes "Pet", "Animal", and "Dog"
    When I add "Dog" as a subclass of "Animal"
    And I add "Dog" as a subclass of "Pet"
    Then "Dog" has both "Animal" and "Pet" in its sub_class_of list
