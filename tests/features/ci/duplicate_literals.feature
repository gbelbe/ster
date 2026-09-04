Feature: Duplicated string literal ratchet (SonarQube S1192)
  CI blocks a change that introduces a new duplicated string literal (the same
  literal, at least 5 characters, appearing 3+ times in one file) or worsens
  an existing one, while grandfathering duplication that was already there —
  same diff-aware ratchet as complexity, applied to S1192.

  Scenario: A literal newly duplicated 3 times in one file fails
    Given a literal absent from the base
    And its occurrence count in the change is 3
    Then the duplicate-literal check reports a violation

  Scenario: A literal duplicated only twice passes
    Given a literal absent from the base
    And its occurrence count in the change is 2
    Then the duplicate-literal check reports no violation

  Scenario: Adding another repeat of an already-duplicated literal fails
    Given a literal with base occurrence count 3
    And its occurrence count in the change is 5
    Then the duplicate-literal check reports a violation

  Scenario: An untouched already-duplicated literal is grandfathered
    Given a literal with base occurrence count 6
    And its occurrence count in the change is 6
    Then the duplicate-literal check reports no violation

  Scenario: Removing a repeat of an already-duplicated literal passes
    Given a literal with base occurrence count 6
    And its occurrence count in the change is 4
    Then the duplicate-literal check reports no violation
