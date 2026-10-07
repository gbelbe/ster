Feature: Embedded map and timeline pages
  As a page that shows a result next to its answer, such as the agent app
  I want ster's map and timeline pages to open without their own chrome
  So that I can show them in a frame, with the query carried in the address

  Scenario: The map opens without its header, query box and details panel when embedded
    Given a running ster API with a minimal taxonomy
    When the client requests "/map?embed=1"
    Then the response status is 200
    And the page hides "header"
    And the page hides "#query-panel"
    And the page hides "aside"
    And the page does not hide "#map"

  Scenario: The map is unchanged when not embedded
    Given a running ster API with a minimal taxonomy
    When the client requests "/map"
    Then the response status is 200
    And the page is not embedded

  Scenario: An embedded map still runs the query in the address
    Given a running ster API with a minimal taxonomy
    When the client requests "/map?q=SELECT%20%3Fs%20WHERE%20%7B%3Fs%20%3Fp%20%3Fo%7D&embed=1"
    Then the page hides "header"
    And the body contains "SELECT ?s WHERE"

  Scenario Outline: Which values of embed turn it on
    Given a running ster API with a minimal taxonomy
    When the client requests "/map?embed=<value>"
    Then the page <effect>

    Examples:
      | value | effect                |
      | 1     | is embedded           |
      | true  | is embedded           |
      | 0     | is not embedded       |
      | false | is not embedded       |

  Scenario: The timeline opens without its header and query box when embedded
    Given a running ster API with a minimal taxonomy
    When the client requests "/timeline?embed=1"
    Then the response status is 200
    And the page hides "header"
    And the page hides "#qbox"
    And the page does not hide "#tl"

  Scenario: The timeline is unchanged when not embedded
    Given a running ster API with a minimal taxonomy
    When the client requests "/timeline"
    Then the page is not embedded

  Scenario: An embedded timeline keeps its date range
    Given a running ster API with a minimal taxonomy
    When the client requests "/timeline?embed=1&after=2025-01-01&before=2026-01-01"
    Then the page hides "header"
    And the body contains "2025-01-01"
    And the body contains "2026-01-01"
