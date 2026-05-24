Feature: Proactive cache warming after ontology save

  Scenario: graph cache is populated after warm_graph_caches
    Given a valid TTL file on disk
    And the graph and URI caches are empty
    When warm_graph_caches is called with that file
    Then the graph cache contains a fresh entry for that file

  Scenario: URI index cache is populated after warm_graph_caches
    Given a valid TTL file on disk
    And the graph and URI caches are empty
    When warm_graph_caches is called with that file
    Then the URI index cache contains a fresh entry for that file

  Scenario: stale graph cache entry is evicted before re-warming
    Given a valid TTL file on disk with an outdated cache entry
    When warm_graph_caches is called with that file
    Then the stale entry is gone and a fresh entry is present in the graph cache

  Scenario: run_query reuses warm cache without re-parsing
    Given a valid TTL file on disk
    And the graph and URI caches are empty
    And warm_graph_caches has already been called
    When run_query is called with that file
    Then load_graph is not invoked a second time
