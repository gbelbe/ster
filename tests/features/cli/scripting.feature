Feature: ster can be run from a script or a CI job
  As someone automating checks on an ontology
  I want ster to never wait for an answer and to exit with a meaningful code
  So that a CI step fails for the right reason and says why

  Scenario: A clean file validates with exit code 0
    Given a valid taxonomy file
    When a script runs "ster validate --file" on it
    Then ster exits with code 0

  Scenario: Validation problems exit with code 1
    Given a taxonomy file with a concept that has no label
    When a script runs "ster validate --file" on it
    Then ster exits with code 1

  Scenario: A missing file exits with code 3
    When a script runs "ster validate --file" on a file that does not exist
    Then ster exits with code 3

  Scenario: A broken file exits with code 4
    Given a file that is not valid Turtle
    When a script runs "ster validate --file" on it
    Then ster exits with code 4

  Scenario: A question with no terminal to answer it exits with code 2
    Given a folder holding one taxonomy file
    When a script with no terminal runs "ster validate" there
    Then ster exits with code 2
    And the error names the question and says to pass --file

  Scenario: An unexpected error is one line, not a traceback
    Given a valid taxonomy file
    And ster will hit an unexpected error
    When a script runs "ster validate --file" on it
    Then ster exits with code 5
    And the error is one line that mentions STER_DEBUG=1

  Scenario: Every command's help shows examples
    Then every command's --help has an Examples section
