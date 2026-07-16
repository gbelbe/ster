Feature: New-TUI — the Textual ontology browser

  A modern, keyboard- and mouse-driven tree browser for ontologies, reached via
  `ster show` or the home-screen menu. It shows classes (with their
  individuals nested), properties and SKOS schemes, with a fuzzy search palette
  and a progressive-disclosure detail panel.

  Background:
    Given the zoo ontology is open in the New-TUI

  Scenario: The tree shows classes, their nested individuals, and properties
    Then the tree contains the class "Dog"
    And the individual "Rex" is nested under the class "Dog"
    And the tree contains the property "has owner"

  Scenario: Properties have their own pane, separate from the class hierarchy
    When I inspect the navigation panes
    Then the property "has owner" is in the properties pane
    And the class "Animal" stays in the main tree, not the properties pane

  Scenario: Moving the cursor updates the detail panel
    When I move the cursor down to the class "Person"
    Then the detail panel shows "Person"

  Scenario: Fuzzy search jumps to a matching entity and shows its detail
    When I search for "rex"
    Then the detail panel shows "Rex"
    And the detail panel shows its owner "Alice"

  Scenario: The detail panel surfaces a class's most important facts
    When I select the class "Dog"
    Then the detail panel shows the comment "Loyal domestic companion."

  Scenario: Arrow keys move between the tree and the detail rows (no Tab needed)
    When I step right into the detail panel, down a row, then left back to the tree
    Then a detail row was focused along the way
    And the tree is focused at the end

  Scenario: Arrow keys wrap around the tree (reach the last node from the top)
    When I press up from the top of the tree
    Then the tree cursor lands on the last node

  Scenario: Expanding the whole tree reveals deep nodes
    When I expand the whole tree
    Then the class "Dog" is visible in the tree

  Scenario: Searching for an unknown entity leaves the view unchanged
    When I search for "https://example.org/zoo/Nonexistent"
    Then the detail panel still shows the overview

  Scenario: Browsing a SKOS concept scheme
    Given a SKOS scheme "Animals" with concepts "Cat" and "Dog" is open in the New-TUI
    Then the tree contains the scheme "Animals"
    And selecting the concept "Cat" shows its definition "A small feline."

  Scenario: Launching the New-TUI from the command line
    When I run "ster show" on the zoo ontology
    Then the browser is launched with that ontology
