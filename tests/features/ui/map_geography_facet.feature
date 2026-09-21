Feature: Reaching the geography from the filter strip

  The hierarchy was only reachable by finding a shape on the map and clicking
  it, which is hard when the shape is small, hidden under markers, or off
  screen. The tiers now appear as chips beside the other filters.

  A tier is named by the class ster already resolved for the place, so an
  ontology of continents and countries gets those words and an ontology of
  sites and floors gets its own, with nothing here naming either.

  Scenario: The tiers appear as chips
    When the map page is rendered
    Then the strip offers a row of geography chips
    And the chips are grouped by the tier's own class name

  Scenario: Picking a place goes there
    When the map page is rendered
    Then picking a geography chip drills to that place
    And a geography chip never becomes a filter

  Scenario: Only tiers that offer a choice are shown
    When the map page is rendered
    Then a tier holding a single place is left out
    And only the nearest tier below the place in focus is offered

  Scenario: The chips cost no extra request
    When the map page is rendered
    Then the tiers are built from the ancestors already in the payload
    And ancestors are resolved through an index rather than a scan
