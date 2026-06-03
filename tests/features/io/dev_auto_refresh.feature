Feature: The dev pages auto-refresh to mirror the committed ontology

  After a taxonomy is committed through ster, the dev channel is rebuilt so
  ontology/dev/ always reflects the latest ontology. The artifacts are written
  to disk (a Turtle file and a pyLODE HTML page) but never committed, and the
  source file is left untouched.

  Scenario: Regenerating dev writes a fresh Turtle and HTML page
    Given an ontology file with a version
    When the dev artifacts are regenerated for it
    Then ontology/dev/ contains a Turtle file and an HTML page

  Scenario: The dev pages reflect the current ontology content
    Given an ontology file containing a class "Widget"
    When the dev artifacts are regenerated for it
    Then the dev Turtle file mentions "Widget"

  Scenario: Regeneration leaves the source file untouched
    Given an ontology file with a version
    When the dev artifacts are regenerated for it
    Then the source file content is unchanged

  Scenario: An ontology with no version still publishes dev
    Given an ontology file with no version set
    When the dev artifacts are regenerated for it
    Then ontology/dev/ contains a Turtle file and an HTML page
