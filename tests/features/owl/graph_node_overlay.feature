Feature: Explore a node, open its individuals, and see what it relates to

  Hovering a node offers two actions. "explore relations" (or "extend relations"
  once a subgraph is open) grows the picture from that node. Below it, a class
  that holds individuals the server withheld offers to show them, and offers to
  put them away again once they are open — a class holding none offers nothing.

  Clicking a node does not change the shape of the graph. It highlights: the node
  itself, everything one step away, and the whole subClassOf chain above it, so a
  node can be read in the context of the hierarchy it belongs to.

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

  # ── the individuals button ──────────────────────────────────────────────────

  Scenario: A class holding withheld individuals offers to show them
    When I load the ster graph app asset
    Then the app wires the show-individuals label
    And the individuals button opens the class through the class-individuals fetch

  Scenario: A class whose individuals are open offers to put them away
    When I load the ster graph app asset
    Then the app wires the hide-individuals label
    And the individuals label depends on whether the class is already open

  Scenario: A class holding no individuals gets no button
    When I load the ster graph app asset
    Then the individuals button is shown only when the node holds individuals

  Scenario: An offline page does not offer to show individuals
    When I load the ster graph app asset
    Then the individuals button is withheld when there is no api token

  # ── clicking a node ─────────────────────────────────────────────────────────

  Scenario: Clicking a node highlights it with its neighbours and its parent chain
    When I load the ster graph app asset
    Then the app defines a parent-chain walk
    And the highlight keeps the node and everything one step away
    And the highlight keeps the whole subClassOf chain above the node
    And the parent chain of an individual starts at the classes it instantiates

  Scenario: Clicking a node no longer opens its individuals
    When I load the ster graph app asset
    Then tapping a node does not open its individuals

  Scenario: Hiding a node with its parents is gone
    When I load the ster graph app asset
    Then the app defines no hide-node-and-parents action

  # ── the rendered page ───────────────────────────────────────────────────────

  Scenario: The rendered page exposes the explore and individuals buttons
    Given an ontology with an individual "Rex" of class "Animal"
    When I render the graph page for interaction
    Then the page contains the explore overlay button
    And the page contains the individuals overlay button
    And the page contains no hide overlay button
