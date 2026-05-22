Feature: Server configuration persistence
  As a ster user
  I want my server URL and port to be saved across sessions
  So that I don't have to reconfigure on every launch

  Scenario: Load defaults when no config file exists
    Given no server config file exists
    When I load the server config
    Then the URL is "http://127.0.0.1"
    And the port is 8765

  Scenario: Default port equals the API_PORT constant
    Given no server config file exists
    When I load the server config
    Then the port equals the API_PORT constant

  Scenario: Save and reload a custom URL
    Given no server config file exists
    When I save server config with URL "http://192.168.1.10" and port 8765
    And I load the server config
    Then the URL is "http://192.168.1.10"

  Scenario: Save and reload a custom port
    Given no server config file exists
    When I save server config with URL "http://127.0.0.1" and port 9000
    And I load the server config
    Then the port is 9000

  Scenario: Port is stored as an integer
    Given no server config file exists
    When I save server config with URL "http://127.0.0.1" and port 9000
    And I load the server config
    Then the port is an integer
