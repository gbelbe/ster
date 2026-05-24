Feature: rdflib SPARQL plugin pre-loading during cache warm

  In order to avoid a ~23 s delay on the user's first Ctrl+R query,
  warm_graph_caches runs a trivial LIMIT 0 query on the freshly-built graph
  so that rdflib's importlib.metadata plugin discovery happens in the background.

  Scenario: Pre-load query fires after cache is populated
    Given a valid TTL file on disk
    And the graph and URI caches are empty
    And rdflib SPARQL queries are being tracked
    When warm_graph_caches is called with that file
    Then a LIMIT 0 query was executed on the cached graph

  Scenario: Pre-load exception does not abort cache warming
    Given a valid TTL file on disk
    And the graph and URI caches are empty
    And rdflib SPARQL queries will raise an exception
    When warm_graph_caches is called with that file
    Then warm_graph_caches completes without raising
    And the graph cache contains a fresh entry for that file

  Scenario: Pre-load is skipped when graph is absent from cache
    Given a valid TTL file on disk
    And the graph and URI caches are empty
    And the graph cache is cleared between build and pre-load
    And rdflib SPARQL queries are being tracked
    When warm_graph_caches is called with that file
    Then no LIMIT 0 query was attempted
