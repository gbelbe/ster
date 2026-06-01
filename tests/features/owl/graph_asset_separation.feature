Feature: ster graph code is separated from the vendored Cytoscape library

  So that upgrading Cytoscape.js is seamless and never overwrites ster's own
  graph interaction and update code, the application layer lives in a versioned
  repo asset and is emitted as its own script, distinct from the library blob
  and from the per-render data injection.

  Scenario: The app layer is a versioned repo asset
    When I load the ster graph app asset
    Then the asset is non-empty
    And the asset wires up the Cytoscape factory

  Scenario: The rendered page emits three distinct script layers
    Given an ontology with an individual "Rex" of class "Animal"
    When I render the graph page with a stub Cytoscape library
    Then the page contains the vendored library layer
    And the page contains the data injection layer
    And the page contains the app asset layer

  Scenario: The app code does not live inside the library script
    Given an ontology with an individual "Rex" of class "Animal"
    When I render the graph page with a stub Cytoscape library
    Then the app asset appears after the library script closes

  Scenario: Upgrading the library leaves the app code untouched
    Given an ontology with an individual "Rex" of class "Animal"
    When I render the page with the old library and again with a new library
    Then the app layer is byte-for-byte identical across both renders

  Scenario: Ontology data is injected, not baked into the app asset
    Given an ontology with an individual "Rex" of class "Animal"
    When I render the graph page with a stub Cytoscape library
    Then the individual data appears in the page
    But the app asset carries no per-ontology data
