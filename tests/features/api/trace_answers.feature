Feature: An agent's answer and resume id are kept with its query trace
  The traces record what an agent asked of the graph. The answer it gave and the
  session it can be resumed with never pass through ster, so whoever ran the agent
  reports them, and they are kept beside the runs they rest on.

  Background:
    Given a running ster API with a minimal taxonomy

  Scenario: An answer is recorded and listed
    Given query tracing is on
    When the runner reports the answer "turn1" to "How many classes?" saying "Two." from run "run-aaa" resumable as "sess-9"
    Then the API accepts it
    And the listed answers hold "turn1" with answer "Two." and resume id "sess-9"

  Scenario: Reporting needs tracing
    Given query tracing is off
    When the runner reports the answer "turn1" to "How many classes?" saying "Two." from run "run-aaa" resumable as "sess-9"
    Then the API refuses with status 409

  Scenario: Reporting needs the token
    Given query tracing is on
    When a client reports an answer without the token
    Then the API refuses with status 401

  Scenario: A report with no question is refused
    Given query tracing is on
    When the runner reports an answer with no question
    Then the API refuses with status 422

  Scenario: An answer is attached to the agent session its runs belong to
    Given query tracing is on
    And a recorded run "run-aaa" in the project
    When the runner reports the answer "turn1" to "How many classes?" saying "Two." from run "run-aaa" resumable as "sess-9"
    Then the agent session of that run carries the answer "Two."
