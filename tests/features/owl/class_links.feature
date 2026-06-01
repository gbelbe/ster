Feature: Explore the linked classes around a class

  Exploring a class shows the classes it is linked to: its superclass trail and
  every class connected to it by an object property — both where the class is
  the property's domain (→ range class) and where it is the range (← domain
  class), drawn as directed, property-labelled edges.

  Background:
    Given classes where "Person" is a subclass of "Agent"
    And object property "owns" has domain "Person" and range "Pet"
    And object property "employs" has domain "Company" and range "Person"
    And "Unrelated" is a class linked to nothing

  Scenario: The focus class is present
    When I explore links for class "Person"
    Then class node "Person" is present

  Scenario: Superclasses are included as a trail
    When I explore links for class "Person"
    Then class node "Agent" is present
    And there is a subClassOf class-edge from "Person" to "Agent"

  Scenario: Range class via an outgoing object property is included
    When I explore links for class "Person"
    Then class node "Pet" is present
    And there is an object-property class-edge from "Person" to "Pet" labelled "owns"

  Scenario: Domain class via an incoming object property is included
    When I explore links for class "Person"
    Then class node "Company" is present
    And there is an object-property class-edge from "Company" to "Person" labelled "employs"

  Scenario: Unrelated classes are excluded
    When I explore links for class "Person"
    Then class node "Unrelated" is absent

  Scenario: Superclasses of object-property-linked classes are included
    Given classes where "Pet" is a subclass of "LivingBeing"
    When I explore links for class "Person"
    Then class node "LivingBeing" is present
    And there is a subClassOf class-edge from "Pet" to "LivingBeing"
