Feature: Focused graph from OWL class in tree view
  As a user browsing an OWL class hierarchy in the tree view
  I want to launch a graph visualization centred on the selected class
  So that I can explore its subclasses and individuals without loading the full ontology

  Background:
    Given an ontology with "Animal", "Dog" (subclass of Animal), "Cat" (subclass of Animal)
    And "Animal" has individual "Simba" and "Dog" has individual "Fido"
    And "Bird" is an unrelated root class with individual "Tweety"

  Scenario: Root class is in focused graph
    When I build a focused graph rooted at "Animal"
    Then the node for "Animal" is present

  Scenario: Direct subclass is included
    When I build a focused graph rooted at "Animal"
    Then the node for "Dog" is present

  Scenario: Transitive subclass is included
    Given "Puppy" is a subclass of "Dog"
    When I build a focused graph rooted at "Animal"
    Then the node for "Puppy" is present

  Scenario: Individual of root class is included
    When I build a focused graph rooted at "Animal"
    Then the node for "Simba" is present

  Scenario: Individual of subclass is included
    When I build a focused graph rooted at "Animal"
    Then the node for "Fido" is present

  Scenario: Sibling class is excluded
    When I build a focused graph rooted at "Dog"
    Then the node for "Cat" is absent

  Scenario: Unrelated class is excluded
    When I build a focused graph rooted at "Animal"
    Then the node for "Bird" is absent

  Scenario: Individual of unrelated class is excluded
    When I build a focused graph rooted at "Animal"
    Then the node for "Tweety" is absent

  Scenario: Layout is always cose for focused OWL graphs
    When I build a focused graph rooted at "Animal"
    Then the graph layout is "cose"
