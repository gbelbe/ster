Feature: Inline lint check before commit

  Scenario: Clean file — lint passes and commit proceeds
    Given a valid SKOS taxonomy file with no violations
    And a repo directory
    When the user runs the pre-commit lint check
    Then the lint result shows no violations
    And the commit is not blocked

  Scenario: File with errors — violations shown, user warned
    Given a taxonomy file with SKOS errors
    And a repo directory
    When the user runs the pre-commit lint check
    Then the lint result shows errors
    And the commit is blocked

  Scenario: File with errors — user aborts
    Given a taxonomy file with SKOS errors
    And a repo directory
    When the user runs the pre-commit lint check and declines to proceed
    Then the pre-commit check returns False

  Scenario: File with errors — user proceeds anyway
    Given a taxonomy file with SKOS errors
    And a repo directory
    When the user runs the pre-commit lint check and confirms to proceed
    Then the pre-commit check returns True

  Scenario: Warnings only with default fail_on error — does not block
    Given a taxonomy file with SKOS warnings only
    And a repo directory
    When the user runs the pre-commit lint check
    Then the lint result shows warnings
    And the commit is not blocked

  Scenario: onto-ci.yml sets fail_on warning — warnings block commit
    Given a taxonomy file with SKOS warnings only
    And a repo directory with onto-ci.yml setting fail_on to warning
    When the user runs the pre-commit lint check and confirms to proceed
    Then the lint result shows warnings
    And the pre-commit check returns True
