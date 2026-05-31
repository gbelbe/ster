Feature: Graph class-order filter buttons

  Background:
    Given a taxonomy with root class "Animal" and subclass "Dog" under it

  Scenario: Hide first-order classes button is rendered
    When I render the filter VOWL graph HTML
    Then the filter HTML contains button id "ft-first-order"

  Scenario: Hide second-order classes button is rendered
    When I render the filter VOWL graph HTML
    Then the filter HTML contains button id "ft-second-order"

  Scenario: toggleFirstOrderClasses JavaScript function is present
    When I render the filter VOWL graph HTML
    Then the filter HTML contains the toggleFirstOrderClasses function

  Scenario: toggleSecondOrderClasses JavaScript function is present
    When I render the filter VOWL graph HTML
    Then the filter HTML contains the toggleSecondOrderClasses function

  Scenario: Buttons auto-hide when there are no OWL classes
    Given a SKOS-only taxonomy with a concept
    When I render the filter VOWL graph HTML
    Then the filter HTML contains code to hide ft-first-order when empty
    And the filter HTML contains code to hide ft-second-order when empty
