Feature: Git-tag-driven semver ontology versioning

  A stable publish reads the latest ontology git tag, applies a semver bump,
  stamps the new version into the source file, commits it, and creates the
  corresponding ontology tag. Ontology tags live in the "<stem>/vX.Y.Z"
  namespace, independent of the bare PyPI package tags.

  Scenario: First stable publish seeds 0.1.0 then bumps
    Given an ontology repo with no ontology tags
    When I perform a stable release with bump "minor"
    Then the release version is "0.2.0"
    And the tag "onto/v0.2.0" exists in the repo
    And the source file contains owl:versionInfo "0.2.0"

  Scenario: Subsequent patch release from an existing tag
    Given an ontology repo already tagged "onto/v1.2.0"
    When I perform a stable release with bump "patch"
    Then the release version is "1.2.1"
    And the tag "onto/v1.2.1" exists in the repo

  Scenario: Major bump for a breaking change
    Given an ontology repo already tagged "onto/v1.2.0"
    When I perform a stable release with bump "major"
    Then the release version is "2.0.0"
    And the tag "onto/v2.0.0" exists in the repo

  Scenario: Ontology tags never collide with the PyPI package tags
    Given an ontology repo already tagged "v0.7.0"
    When I perform a stable release with bump "patch"
    Then the release version is "0.1.1"
    And the tag "onto/v0.1.1" exists in the repo

  Scenario: The release is committed
    Given an ontology repo with no ontology tags
    When I perform a stable release with bump "patch"
    Then a commit "release(onto): v0.1.1" exists in the repo

  Scenario: The release is pushed to the configured remote
    Given an ontology repo with a remote and no ontology tags
    When I perform a stable release with bump "patch"
    Then the tag "onto/v0.1.1" exists in the remote
