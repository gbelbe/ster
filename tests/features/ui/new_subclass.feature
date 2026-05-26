Feature: Create a new subclass from the class detail panel
  As an ontology editor
  I want to create a new OWL class that is a subclass of the current class
  So that I can grow a class hierarchy without leaving the detail view

  Scenario: Detail panel shows a Subclasses section with direct children
    Given a taxonomy with class "Animal" that has a subclass "Dog"
    When I build the detail fields for "Animal"
    Then the detail panel contains a "Subclasses" separator
    And the detail panel shows "Dog" as a child row with key "subclass:https://example.org/Dog"

  Scenario: Detail panel shows New subclass action in the Subclasses section
    Given a taxonomy with class "Animal"
    When I build the detail fields for "Animal"
    Then the detail panel contains a "New subclass" action after the Subclasses separator

  Scenario: Detail panel no longer contains the old link_subclass picker action
    Given a taxonomy with class "Animal"
    When I build the detail fields for "Animal"
    Then no detail field has action "link_subclass"

  Scenario: Activating New subclass creates the class and the relationship
    Given a taxonomy with class "Animal"
    When the new subclass URI "https://example.org/Cat" is confirmed on "Animal"
    Then "https://example.org/Cat" exists in the taxonomy owl_classes
    And "https://example.org/Animal" is in Cat's sub_class_of list

  Scenario: Circular hierarchy is rejected and no class is created
    Given a taxonomy where "Animal" is a subclass of "LivingThing"
    When the new subclass URI "https://example.org/LivingThing" is confirmed on "Animal"
    Then a CircularHierarchyError is raised
