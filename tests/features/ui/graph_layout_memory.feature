Feature: The graph remembers where I left its nodes
  As someone who arranges the graph by hand to make it readable
  I want my node positions kept in the project, and kept true as the ontology changes
  So that reopening ster later does not throw my work away

  Background:
    Given an ontology with the classes "Animal", "Dog" and "Cat"
    And I left "Dog" at 100, 200 in the graph

  Scenario: Nodes I moved are where I left them when I reopen ster
    When ster is reopened on the same project
    Then the graph places "Dog" at 100, 200

  Scenario: A deleted node's position is removed from the layout file
    When "Dog" is deleted from the ontology
    And the graph saves any position
    Then the layout file no longer mentions "Dog"

  Scenario: A renamed node keeps its position
    When "Dog" is renamed to "Hound"
    Then the graph places "Hound" at 100, 200

  Scenario: Adding a relation moves nothing
    When "Dog" becomes a subclass of "Animal"
    And ster is reopened on the same project
    Then the graph places "Dog" at 100, 200

  Scenario: Reset layout forgets the saved positions
    When I reset the layout
    Then the graph has no remembered positions

  Scenario: An unreadable layout file is ignored and replaced on the next save
    Given the layout file has been corrupted
    Then the graph has no remembered positions
    When I leave "Cat" at 5, 5
    Then the graph places "Cat" at 5, 5
