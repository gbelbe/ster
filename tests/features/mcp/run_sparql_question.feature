Feature: A run_sparql call says in plain words what it looks for
  Most MCP clients cannot set the _meta field that carries the step question, so
  run_sparql also takes it as a "question" argument. Either way it lands in the
  query trace, where it titles the step.

  Background:
    Given a graph with a few concepts
    And query tracing is on

  Scenario: The tool offers the argument, and it is optional
    Then run_sparql declares an optional "question" argument

  Scenario: The question argument is recorded in the trace
    When an agent runs a query with the question "Count the concepts"
    Then the trace of that call records the question "Count the concepts"
    And the answer does not ask for the question again

  Scenario: The _meta question wins over the argument
    When an agent runs a query with the question "From the argument" and the metadata question "From the metadata"
    Then the trace of that call records the question "From the metadata"

  Scenario: A query with no question is told to give one
    When an agent runs a query with no question
    Then the trace of that call has no question
    And the answer asks for the question, naming the argument

  Scenario Outline: A question that cannot be used is ignored
    When an agent runs a query with the unusable question <value>
    Then the trace of that call has no question

    Examples:
      | value   |
      | "   "   |
      | 42      |
      | too-long |
