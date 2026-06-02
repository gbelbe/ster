Feature: Extend and hide nodes within a graph subgraph

  Once a subgraph has been opened by exploring a node, the hover overlay lets the
  user grow the picture incrementally rather than replacing it: "explore
  relations" becomes "extend relations" and merges the hovered node's
  neighbourhood into the current graph. A second overlay button hides a node
  together with its parent trail — an individual drops with its class and
  superclasses, a class drops with its superclasses — while parents still needed
  by other visible nodes are kept.

  Scenario: The overlay offers explore on the full graph and extend in a subgraph
    When I load the ster graph app asset
    Then the app wires the explore-relations label
    And the app wires the extend-relations label
    And the explore overlay label depends on whether a subgraph is open

  Scenario: Extending a node is additive, not a replacement
    When I load the ster graph app asset
    Then the app defines an extend-node action
    And extending merges new elements without clearing the whole graph
    And extending de-duplicates edges by their endpoints and type

  Scenario: Hiding an individual drops its class and superclass trail
    When I load the ster graph app asset
    Then the app defines a hide-node-and-parents action
    And hiding an individual follows its rdf:type and subClassOf trail

  Scenario: Hiding a class drops only its superclass trail
    When I load the ster graph app asset
    Then hiding a class follows only its subClassOf trail

  Scenario: A parent still needed by another visible node is kept
    When I load the ster graph app asset
    Then hiding keeps a parent that another visible node depends on

  Scenario: The rendered page exposes both overlay buttons
    Given an ontology with an individual "Rex" of class "Animal"
    When I render the graph page for interaction
    Then the page contains the explore overlay button
    And the page contains the hide overlay button
