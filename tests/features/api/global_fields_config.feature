Feature: Global fields — Local Server Configuration section
  As a ster user
  I want the Config/Setup panel to show computed serving URLs
  So that I can easily copy them for use in browsers or RDF clients

  Scenario: Section is labelled "Local Server Configuration"
    Given global fields built without a workspace
    Then the first separator is "Local Server Configuration"

  Scenario: URL fields appear when an ontology slug is provided
    Given global fields built with slug "animals" on port 8765
    Then a field "ontology:serving_url" exists with value "http://127.0.0.1:8765/animals"
    And a field "ontology:viz_url" exists with value "http://127.0.0.1:8765/viz"

  Scenario: URL fields are absent when no slug is provided
    Given global fields built without a slug
    Then no field "ontology:serving_url" exists
    And no field "ontology:viz_url" exists
