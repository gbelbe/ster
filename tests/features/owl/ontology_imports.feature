Feature: Ontology import discovery
  As a user editing an OWL ontology
  When I want to relate individuals of a class that subclasses an external class
  I want ster to lazily discover compatible external properties
  So that I can pick them in the relate picker without manually editing prefixes

  Background:
    Given a local taxonomy with a class "kai:Person"

  Scenario: Discover external class references from rdfs:subClassOf
    Given "kai:Person" is declared as "rdfs:subClassOf foaf:Person"
    When I scan for external class references
    Then the result includes the URI for "foaf:Person"

  Scenario: Discover external class references from rdf:type on individuals
    Given an individual typed as "schema:Person"
    When I scan for external class references
    Then the result includes the URI for "schema:Person"

  Scenario: No external references when all classes are local
    Given all classes and individuals reference only local URIs
    When I scan for external class references
    Then the result is empty

  Scenario: Derive namespace URL from a hash-style URI
    Given the URI "http://xmlns.com/foaf/0.1/Person"
    When I derive the namespace URL
    Then the namespace URL is "http://xmlns.com/foaf/0.1/"

  Scenario: Derive namespace URL from a slash-style URI
    Given the URI "https://schema.org/Person"
    When I derive the namespace URL
    Then the namespace URL is "https://schema.org/"

  Scenario: Return cached ontology without network fetch
    Given a cached ontology for "http://xmlns.com/foaf/0.1/"
    When I fetch the ontology for "http://xmlns.com/foaf/0.1/"
    Then the cached graph is returned
    And no HTTP request is made

  Scenario: Fetch and cache a new ontology
    Given no cached ontology for "http://xmlns.com/foaf/0.1/"
    And the URL "http://xmlns.com/foaf/0.1/" is reachable and returns RDF
    When I fetch the ontology for "http://xmlns.com/foaf/0.1/"
    Then the graph is returned
    And the graph is written to the cache

  Scenario: Return empty graph when ontology URL is unreachable
    Given no cached ontology for "http://xmlns.com/foaf/0.1/"
    And the URL "http://xmlns.com/foaf/0.1/" is not reachable
    When I fetch the ontology for "http://xmlns.com/foaf/0.1/"
    Then an empty graph is returned
    And no exception is raised

  Scenario: Include property whose domain directly matches the class
    Given an external ontology defining "foaf:knows" with domain "foaf:Person"
    When I get properties for "foaf:Person" with no superclasses
    Then "foaf:knows" is included in the result

  Scenario: Include property whose domain matches a superclass
    Given an external ontology defining "foaf:knows" with domain "foaf:Agent"
    When I get properties for "foaf:Person" with superclass "foaf:Agent"
    Then "foaf:knows" is included in the result

  Scenario: Include property with no declared domain
    Given an external ontology defining "foaf:knows" with no domain
    When I get properties for "foaf:Person" with no superclasses
    Then "foaf:knows" is included in the result

  Scenario: Suggest merges local and external properties without duplicates
    Given a local taxonomy with property "kai:knows" for "kai:Person"
    And an external ontology defining "foaf:knows" for "foaf:Person"
    And "kai:Person" is declared as "rdfs:subClassOf foaf:Person"
    When I suggest properties for an individual of type "kai:Person"
    Then the result contains "kai:knows"
    And the result contains "foaf:knows"
    And there are no duplicate URIs
