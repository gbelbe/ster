Feature: Fixed API server port
  As a user of the kai extension
  I want the ster API server to always bind to port 8765
  So that the extension can connect without manual configuration

  Scenario: API_PORT constant has the expected value
    Given the ster viz_vowl module
    When I read the API_PORT constant
    Then API_PORT equals 8765

  Scenario: The server URL uses the fixed port
    Given the ster viz_vowl module
    When I read the API_PORT constant
    Then the server URL resolves to "http://127.0.0.1:8765/"

  Scenario: The kai extension defaults to the fixed port
    Given the kai extension popup.js source
    When I read the DEFAULT_API_URL constant
    Then DEFAULT_API_URL equals "http://127.0.0.1:8765"
