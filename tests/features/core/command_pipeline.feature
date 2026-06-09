Feature: End-to-end command pipeline

  Drives sequences of commands through the real TaxonomyService (real atomic
  persistence + the validation gate + optimistic-concurrency versions) against a
  TTL file on disk, asserting both the in-memory model and the reloaded file
  after each step. These chained scenarios are how a front-end (TUI or API)
  exercises the core, so they catch interactions a single-command test misses.

  Scenario: Rename, move, relabel, then delete a concept
    Given an ontology file with concepts "Top", "Other" and "Child" under "Top"
    When I rename "Child" to "Pup"
    Then concept "Pup" exists and "Child" does not
    When I move concept "Pup" under "Other"
    Then concept "Pup" is a child of "Other"
    When I set the "en" pref label of "Pup" to "Puppy"
    Then the saved file has "Puppy" as the "en" pref label of "Pup"
    When I delete concept "Pup"
    Then concept "Pup" does not exist
    And the saved file does not contain "Pup"
    And the file version is 4

  Scenario: Reparent an OWL class then rename it
    Given an ontology file with classes "Animal", "Mammal" and "Dog" under "Animal"
    When I reparent class "Dog" under "Mammal"
    And I rename "Dog" to "Canine"
    Then class "Canine" is a subclass of "Mammal"
    And class "Dog" does not exist

  Scenario: A duplicate-label edit is blocked mid-sequence and the version holds
    Given an ontology file with concepts "Top", "Other" and "Child" under "Top"
    When I rename "Child" to "Pup"
    Then the file version is 1
    When I set the "en" pref label of "Pup" to "Other"
    Then the last command was blocked
    And the file version is 1

  Scenario: A stale optimistic-concurrency write is rejected
    Given an ontology file with concepts "Top", "Other" and "Child" under "Top"
    When I rename "Child" to "Pup"
    And I move concept "Pup" under "Other" based on version 0
    Then the last command was rejected
    And the file version is 1
