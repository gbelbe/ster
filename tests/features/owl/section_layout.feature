Feature: Treeview section layout adapts to ontology content

  Scenario: OWL-only taxonomy shows Properties section before class tree
    Given an OWL-only taxonomy with class "Person"
    When I flatten the tree for display
    Then the flat list contains a Properties section node
    And the Properties section appears before any class node

  Scenario: SKOS-only taxonomy shows no Properties section
    Given a SKOS-only taxonomy with concept "Animal"
    When I flatten the tree for display
    Then the flat list has no Properties section node

  Scenario: Mixed taxonomy shows Properties section before class and concept nodes
    Given a mixed taxonomy with class "Person" and concept "Animal"
    When I flatten the tree for display
    Then the flat list contains a Properties section node
    And the Properties section appears before any class node

  Scenario: In mixed view class nodes appear before concept nodes
    Given a mixed taxonomy with class "Person" and concept "Animal"
    When I flatten the tree for display
    Then class nodes appear before concept nodes in the flat list

  Scenario: Properties section is marked folded when its URI is in the folded set
    Given an OWL-only taxonomy with class "Person"
    When I flatten the tree with the Properties section folded
    Then the Properties section node has is_folded True

  Scenario: Properties section is marked unfolded when its URI is not in the folded set
    Given an OWL-only taxonomy with class "Person"
    When I flatten the tree with the Properties section unfolded
    Then the Properties section node has is_folded False

  Scenario: Property nodes appear inside the expanded Properties section
    Given an OWL-only taxonomy with class "Person" and property "hasAge"
    When I flatten the tree with the Properties section unfolded
    Then the flat list contains a property node for "hasAge"
    And the property node for "hasAge" appears before any class node

  Scenario: Property nodes are hidden when the Properties section is collapsed
    Given an OWL-only taxonomy with class "Person" and property "hasAge"
    When I flatten the tree with the Properties section folded
    Then the flat list has no property node for "hasAge"

  Scenario: Add property action row appears at the bottom of the expanded section
    Given an OWL-only taxonomy with class "Person"
    When I flatten the tree with the Properties section unfolded
    Then the flat list contains an Add property action row

  Scenario: Searching a fully expanded tree finds properties by label
    Given an OWL-only taxonomy with class "Person" and property "hasAge"
    When I build a fully expanded flat tree and search for "hasAge"
    Then the search matches include the property node for "hasAge"

  Scenario: Properties in a collapsed section are absent from the flat list and unsearchable
    Given an OWL-only taxonomy with class "Person" and property "hasAge"
    When I build a flat tree with Properties section collapsed
    Then the flat list has no property node for "hasAge"
