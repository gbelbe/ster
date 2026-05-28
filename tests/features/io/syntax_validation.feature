Feature: Friendly syntax error reporting when loading RDF files
  As a ster user opening a file with a syntax error
  I want a clear message showing the bad line and its number
  So I can fix the source file without decoding raw parser noise

  Scenario: Valid Turtle file loads without error message
    Given a valid Turtle file
    When format_parse_error is called with a successful load exception it never fires
    Then no syntax error is formatted

  Scenario: Turtle file with a newline inside a string literal
    Given a Turtle file with a bare newline inside a quoted label at line 10
    When format_parse_error is called with the parse exception and file path
    Then the formatted message contains a line reference
    And the formatted message contains the word "Syntax"

  Scenario: Turtle file with a syntax error at line 5
    Given a Turtle file with a missing dot at line 5
    When format_parse_error is called with the parse exception and file path
    Then the formatted message contains a line reference

  Scenario: Exception message contains no line number
    Given a parse exception whose message contains no line number
    When format_parse_error is called with the exception and a valid path
    Then the formatted message still contains the exception text
    And no crash occurs

  Scenario: Offending line is very long
    Given a Turtle file whose bad line is 200 characters long
    When format_parse_error is called with the parse exception and file path
    Then the shown line excerpt is at most 120 characters long
