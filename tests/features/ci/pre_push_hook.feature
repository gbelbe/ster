Feature: git pre-push hook enforces CI gate
  As a developer
  I want git push to be blocked when CI has not passed recently
  So that broken code never reaches the remote

  Scenario: push blocked when sentinel file is absent
    Given the CI sentinel file does not exist
    When the pre-push hook runs
    Then the hook exits with code 1
    And the output contains "CI has not been run"

  Scenario: push allowed when sentinel is fresh
    Given the CI sentinel file was written less than 60 minutes ago
    When the pre-push hook runs
    Then the hook exits with code 0

  Scenario: push blocked when sentinel is stale
    Given the CI sentinel file was written more than 60 minutes ago
    When the pre-push hook runs
    Then the hook exits with code 1
    And the output contains "CI result is stale"
