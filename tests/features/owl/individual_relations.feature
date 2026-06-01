Feature: Expand the object-property relations around an individual

  As a user exploring the graph, when I focus on an individual I want a subgraph
  of everything related to it by object properties — the individuals that point
  to it and the individuals it points to (directed, labelled), the class(es) it
  belongs to, and the classes of every related individual.

  Background:
    Given an A-Box where "Fido" owns "Alice" and "Alice" livesIn "Paris"
    And "Alice" is a "Person", "Fido" is a "Dog", "Paris" is a "City"
    And "Bob" is an unrelated "Person"

  Scenario: The focus individual is present
    When I expand relations for "Alice"
    Then node "Alice" is present

  Scenario: Incoming object-property neighbour is included with a directed edge
    When I expand relations for "Alice"
    Then node "Fido" is present
    And there is an object-property edge from "Fido" to "Alice" labelled "owns"

  Scenario: Outgoing object-property neighbour is included with a directed edge
    When I expand relations for "Alice"
    Then node "Paris" is present
    And there is an object-property edge from "Alice" to "Paris" labelled "livesIn"

  Scenario: The class of the focus individual is included
    When I expand relations for "Alice"
    Then node "Person" is present

  Scenario: The classes of related individuals are included
    When I expand relations for "Alice"
    Then node "Dog" is present
    And node "City" is present

  Scenario: Unrelated individuals are excluded
    When I expand relations for "Alice"
    Then node "Bob" is absent

  Scenario: Superclasses of the focus class are included as a trail
    Given "Person" is a subclass of "Agent"
    And "Agent" is a subclass of "Thing"
    When I expand relations for "Alice"
    Then node "Agent" is present
    And node "Thing" is present
    And there is a subClassOf edge from "Person" to "Agent"
    And there is a subClassOf edge from "Agent" to "Thing"

  Scenario: Superclasses of related individuals' classes are included
    Given "Dog" is a subclass of "Animal"
    When I expand relations for "Alice"
    Then node "Animal" is present
    And there is a subClassOf edge from "Dog" to "Animal"
