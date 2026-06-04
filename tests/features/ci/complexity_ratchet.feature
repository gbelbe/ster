Feature: Complexity ratchet
  CI blocks changes that make cyclomatic complexity worse, while
  grandfathering functions that are already over the threshold.

  Scenario: A new function over the threshold fails
    Given a function absent from the base
    And its complexity in the change is 12
    Then the ratchet check reports a violation

  Scenario: Increasing an already-complex function fails
    Given a function with base complexity 18
    And its complexity in the change is 20
    Then the ratchet check reports a violation

  Scenario: Refactoring a complex function down passes
    Given a function with base complexity 18
    And its complexity in the change is 14
    Then the ratchet check reports no violation

  Scenario: An untouched complex function is grandfathered
    Given a function with base complexity 24
    And its complexity in the change is 24
    Then the ratchet check reports no violation

  Scenario: A new function within the threshold passes
    Given a function absent from the base
    And its complexity in the change is 9
    Then the ratchet check reports no violation

  Scenario: Pushing a simple function over the threshold fails
    Given a function with base complexity 8
    And its complexity in the change is 11
    Then the ratchet check reports a violation

  Scenario: Modifying a god-function without reducing it fails
    Given a god-function with base complexity 127
    And you modify it leaving complexity at 127
    Then the ratchet reports a god-function violation

  Scenario: Modifying a god-function and reducing it passes
    Given a god-function with base complexity 127
    And you modify it reducing complexity to 120
    Then the ratchet reports no god-function violation
