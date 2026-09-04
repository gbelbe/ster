Feature: Multi-file selection and editing in ster
  As a taxonomy engineer
  I want to select and open multiple taxonomy files simultaneously
  So that I can view and edit concepts across multiple files in a unified workspace

  Scenario: Opening all project files
    Given a project with multiple taxonomy files "a.ttl" and "b.ttl"
    When I select the open all project files option
    Then a workspace with both "a.ttl" and "b.ttl" is loaded

  Scenario: Comma-separated file selection
    Given a project with multiple taxonomy files "a.ttl", "b.ttl", and "c.ttl"
    When I enter comma-separated file numbers "2, 4"
    Then a workspace with "a.ttl" and "c.ttl" is loaded
