Feature: VOWL hierarchical layout optimisation
  As a user visualising an OWL ontology
  I want classes arranged so their relations do not cross
  And individuals clustered close to their class without hiding inter-class edges

  Background:
    Given a root class "Animal" with subclasses "Dog" and "Cat"
    And a separate root class "Tool" with subclass "Hammer"
    And an objectProperty "uses" from "Dog" to "Hammer"
    And individual "Fido" of "Dog" and individual "Kitty" of "Cat"

  Scenario: Root class order puts objectProperty-connected roots adjacent
    When I build the VOWL graph
    Then "Animal" and "Tool" are adjacent in the rootClassOrder

  Scenario: All root classes appear in rootClassOrder
    When I build the VOWL graph
    Then the rootClassOrder contains exactly the root class URIs

  Scenario: Isolated root class is included in rootClassOrder
    Given a further root class "Plant" with no connections
    When I build the VOWL graph
    Then "Plant" appears in the rootClassOrder

  Scenario: Individual nodes carry orbit data
    When I build the VOWL graph
    Then the node for "Fido" has orbitAngle, orbitR, and orbitClassUri

  Scenario: Orbit radius is almost touching the class circle
    When I build the VOWL graph
    Then "Fido"'s orbitR equals the subclass radius plus individual radius plus 5

  Scenario: Multiple individuals of same class have distinct angles
    When I build the VOWL graph
    Then "Fido" and "Kitty" have different orbitAngles

  Scenario: Individual orbit angle faces away from parent class
    Given individual "Pup" of "Dog"
    When I build the VOWL graph
    Then "Pup"'s orbitAngle is not pointing toward "Animal"

  Scenario: Class nodes carry a groupRadius that includes their orbital ring
    When I build the VOWL graph
    Then "Dog"'s groupRadius is larger than its own circle radius

  Scenario: SKOS-only graph has no rootClassOrder
    Given a SKOS taxonomy with a scheme and one concept
    When I build the VOWL graph for the SKOS taxonomy
    Then the graph output has no rootClassOrder key
