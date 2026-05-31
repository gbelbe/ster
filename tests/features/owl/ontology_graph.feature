Feature: Ontology graph data builder (Cytoscape.js format)

  Scenario: Empty taxonomy produces empty nodes and edges
    Given an empty taxonomy
    When I build the full ontology graph
    Then the graph has 0 nodes
    And the graph has 0 edges
    And the graph layout is "cose"

  Scenario: OWL class appears as a class node
    Given a taxonomy with OWL class "Animal"
    When I build the full ontology graph
    Then the graph contains a node for "Animal" of type "class"

  Scenario: OWL individual appears as an individual node
    Given a taxonomy with OWL class "Dog" and individual "Rex" typed as "Dog"
    When I build the full ontology graph
    Then the graph contains a node for "Rex" of type "individual"

  Scenario: subClassOf hierarchy produces a subClassOf edge
    Given a taxonomy with OWL classes "Animal" and "Dog"
    And "Dog" is a subclass of "Animal"
    When I build the full ontology graph
    Then the graph contains a "subClassOf" edge from "Dog" to "Animal"

  Scenario: rdf:type produces an instanceOf edge
    Given a taxonomy with OWL class "Dog" and individual "Rex" typed as "Dog"
    When I build the full ontology graph
    Then the graph contains an "instanceOf" edge from "Rex" to "Dog"

  Scenario: ObjectProperty produces an objectProperty edge with label
    Given a taxonomy with OWL classes "Dog" and "Person"
    And an object property "hasMaster" from "Dog" to "Person"
    When I build the full ontology graph
    Then the graph contains an "objectProperty" edge from "Dog" to "Person"
    And that edge has label "hasMaster"

  Scenario: DatatypeProperty produces a datatypeProperty edge
    Given a taxonomy with OWL class "Person" and a datatype property "name" from "Person"
    When I build the full ontology graph
    Then the graph contains a "datatypeProperty" edge from "Person"

  Scenario: Builtin URI is excluded from subClassOf edges
    Given a taxonomy with OWL class "Dog" whose parent is "owl:Thing"
    When I build the full ontology graph
    Then the graph contains no "subClassOf" edge to "owl:Thing"

  Scenario: OWL-only taxonomy uses cose layout
    Given a taxonomy with OWL class "Animal"
    When I build the full ontology graph
    Then the graph layout is "cose"

  Scenario: Focused graph includes the root class
    Given a taxonomy with OWL classes "Animal", "Dog" subclass of "Animal", "Bird"
    When I build a focused graph on "Animal"
    Then the graph contains a node for "Animal"

  Scenario: Focused graph includes transitive subclasses
    Given a taxonomy with "Animal", "Dog" subclass of "Animal", "Puppy" subclass of "Dog"
    When I build a focused graph on "Animal"
    Then the graph contains a node for "Puppy"

  Scenario: Focused graph excludes sibling classes
    Given a taxonomy with OWL classes "Animal", "Dog" subclass of "Animal", "Cat" subclass of "Animal"
    When I build a focused graph on "Dog"
    Then the graph does not contain a node for "Cat"

  Scenario: Focused graph excludes unrelated root classes
    Given a taxonomy with OWL classes "Animal", "Dog" subclass of "Animal", "Bird"
    When I build a focused graph on "Animal"
    Then the graph does not contain a node for "Bird"

  Scenario: Query result graph includes only matched URIs
    Given a taxonomy with OWL classes "Dog" and "Cat"
    When I build a query result graph matching only "Dog"
    Then the graph contains a node for "Dog"
    And the graph does not contain a node for "Cat"

  Scenario: Query result graph uses cose layout
    Given a taxonomy with OWL class "Dog"
    When I build a query result graph matching only "Dog"
    Then the graph layout is "cose"
