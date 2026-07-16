Feature: Adding and managing external ontology namespaces
  As a user building an ontology
  I want to add external ontology namespaces from within ster
  So that their properties and classes become available without editing the TTL file by hand

  Scenario: Common ontologies list contains well-known namespaces
    When I retrieve the list of common ontologies
    Then the list contains at least 4 entries
    And FOAF is in the list
    And Schema.org is in the list

  Scenario: Adding a namespace registers it in the taxonomy
    Given a taxonomy with no namespace bindings
    When I add namespace "http://xmlns.com/foaf/0.1/" with prefix "foaf"
    Then "foaf" maps to "http://xmlns.com/foaf/0.1/" in namespace_bindings

  Scenario: Adding a namespace that is already registered is idempotent
    Given a taxonomy with "foaf" already bound to "http://xmlns.com/foaf/0.1/"
    When I add namespace "http://xmlns.com/foaf/0.1/" with prefix "foaf"
    Then "foaf" maps to "http://xmlns.com/foaf/0.1/" in namespace_bindings
    And namespace_bindings has exactly 1 entry
