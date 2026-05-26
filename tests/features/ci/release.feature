Feature: Automated release script
  As a maintainer
  I want a single command to version-bump, update docs, and publish
  So that shipping requires no manual file editing and no Claude tokens

  Scenario: Version is bumped in pyproject.toml
    Given pyproject.toml has version "0.4.6"
    When bump_version is called with "0.4.7"
    Then pyproject.toml contains version "0.4.7"

  Scenario: README ASCII banner is updated
    Given README.md has banner line "  v0.4.6"
    When bump_version is called with "0.4.7"
    Then README.md contains banner line "  v0.4.7"

  Scenario: Changelog entry is prepended with version header
    Given README.md has a "## Changelog" section with an existing entry
    And RELEASE_NOTES.md contains "- New feature X"
    When bump_version is called with "0.4.7" and the release notes
    Then README.md contains "### 0.4.7" immediately after "## Changelog"
    And the entry contains "- New feature X"

  Scenario: Existing changelog entries are preserved
    Given README.md has a "## Changelog" section with a "### 0.4.6" entry
    And RELEASE_NOTES.md contains "- New feature X"
    When bump_version is called with "0.4.7" and the release notes
    Then README.md still contains the "### 0.4.6" entry below the new one

  Scenario: Release script blocked when RELEASE_NOTES.md is missing
    Given RELEASE_NOTES.md does not exist
    When release.sh is run with a fresh CI sentinel
    Then the script exits with a non-zero code
    And stderr contains "RELEASE_NOTES"

  Scenario: Release script blocked when CI sentinel is absent
    Given the CI sentinel file does not exist
    When release.sh is run without RELEASE_NOTES.md check
    Then the script exits with a non-zero code
    And stderr contains "CI"
