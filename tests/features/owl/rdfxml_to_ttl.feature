Feature: RDF/XML to Turtle conversion

  # ── Format detection ─────────────────────────────────────────────────────────

  Scenario: .owl extension is identified as RDF/XML serialisation
    Given a file path with extension ".owl"
    Then the detected RDF format is "xml"

  Scenario: .n3 extension is identified as N3 serialisation
    Given a file path with extension ".n3"
    Then the detected RDF format is "n3"

  Scenario: .owl path is recognised as an RDF/XML path
    Given a file path with extension ".owl"
    Then is_rdfxml_path returns True

  Scenario: .ttl path is not recognised as an RDF/XML path
    Given a file path with extension ".ttl"
    Then is_rdfxml_path returns False

  # ── Direct conversion ────────────────────────────────────────────────────────

  Scenario: An RDF/XML file is converted to valid Turtle
    Given an RDF/XML file containing one triple
    When I convert it to Turtle
    Then the output file is valid Turtle
    And the output contains the same triple

  Scenario: A .owl RDF/XML file is converted to valid Turtle
    Given a .owl file containing one triple in RDF/XML format
    When I convert it to Turtle
    Then the output file is valid Turtle
    And the output contains the same triple

  Scenario: A Turtle file is converted to valid RDF/XML
    Given a Turtle file containing one triple
    When I convert it to RDF/XML
    Then the output file is valid RDF/XML
    And the output contains the same triple

  Scenario: convert_to_ttl uses the same stem with .ttl when no output is given
    Given an RDF/XML file named "onto.rdf"
    When I call convert_to_ttl without specifying an output
    Then the output path is "onto.ttl" in the same directory

  # ── ster convert command ─────────────────────────────────────────────────────

  Scenario: ster convert produces a .ttl file from a .rdf file
    Given an RDF/XML file "onto.rdf" on disk
    When I run ster convert on "onto.rdf"
    Then "onto.ttl" exists and is valid Turtle

  Scenario: ster convert with --output writes to the given path
    Given an RDF/XML file "onto.rdf" on disk
    When I run ster convert on "onto.rdf" with output "result.ttl"
    Then "result.ttl" exists and is valid Turtle

  # ── Back-conversion after viewer ─────────────────────────────────────────────

  Scenario: No back-conversion prompt when the .ttl was not modified
    Given a Turtle file and its original "onto.owl"
    And the Turtle file hash is unchanged
    When _maybe_backconvert is called
    Then no prompt is shown

  Scenario: Back-conversion is offered when the .ttl has changed
    Given a Turtle file and its original "onto.owl"
    And the Turtle file hash has changed
    When _maybe_backconvert is called
    Then a prompt asks to convert back to "onto.owl"

  Scenario: Accepting back-conversion writes valid RDF/XML to the original path
    Given a Turtle file and its original "onto.owl"
    And the Turtle file hash has changed
    When the user accepts back-conversion
    Then "onto.owl" contains valid RDF/XML

  Scenario: Declining back-conversion leaves the original file unchanged
    Given a Turtle file and its original "onto.owl"
    And the Turtle file hash has changed
    When the user declines back-conversion
    Then "onto.owl" is unchanged
