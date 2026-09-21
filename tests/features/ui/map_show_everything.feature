Feature: Showing every mapped result, not only the level you are on

  The map draws one tier of the containment hierarchy at a time, which answers
  "what is inside here" but never "show me all of them". Asking for the leaves
  by query cannot work: the server adds every containing place back as context
  so the drill-down has a hierarchy, so the ancestors return whatever the query
  selected. The switch is the way, and it is carried in the URL so a link opens
  the way it was shared.

  Scenario: The map offers a choice between the level and everything
    When the map page is rendered
    Then the page offers a Levels and an Everything mode
    And the page opens in Levels mode

  Scenario: Everything mode draws the leaves rather than a tier
    When the map page is rendered
    Then what is drawn in Everything mode is the leaves of the hierarchy
    And what is drawn in Everything mode ignores the level

  Scenario: Drilling in still narrows what Everything covers
    When the map page is rendered
    Then Everything mode still keeps only what descends from the focus

  Scenario: A link can open the map already showing everything
    Given the map is asked for Everything mode in the URL
    When the map page is rendered for that request
    Then the page opens in Everything mode

  Scenario: Flipping the switch updates the link without navigating
    When the map page is rendered
    Then flipping the switch rewrites the URL in place
    And flipping the switch leaves the level and the focus alone
