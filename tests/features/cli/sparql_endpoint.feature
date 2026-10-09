Feature: Browse an ontology straight from a SPARQL endpoint (read-only)
  As someone whose ontology lives in a triple store such as GraphDB
  I want to open it in ster without exporting a file first
  So that I can browse, query and draw it with the tools I already use

  Background:
    Given a SPARQL endpoint that holds two concepts

  Scenario: Open the default graph of an endpoint
    When I print the endpoint's tree
    Then the tree shows the concept "Tent"
    And the endpoint was asked for a CONSTRUCT of the default graph

  Scenario: Open a named graph
    When I print the endpoint's tree for the named graph "https://example.org/graphs/arch"
    Then the endpoint was asked for that named graph

  Scenario: Open the result of my own CONSTRUCT query
    When I print the endpoint's tree for my own CONSTRUCT query
    Then the endpoint received my query unchanged

  Scenario: The row limit is applied and its truncation is reported
    When I print the endpoint's tree with a row limit of 3
    Then the endpoint was asked for at most 3 rows
    And I am told the row limit was reached

  Scenario: The endpoint is unreachable and the reason is shown
    Given the endpoint is down
    When I print the endpoint's tree
    Then the command fails and says the endpoint could not be reached

  Scenario: Editing is refused because there is no file to save to
    When I open the endpoint in the viewer
    Then editing is refused as read-only

  Scenario: Re-fetching replaces the data without restarting
    When I open the endpoint in the viewer
    And the endpoint then holds a third concept and I press re-fetch
    Then the viewer shows the third concept

  Scenario: The home menu asks for the endpoint and opens it
    When I choose the endpoint entry in the home menu and answer its questions
    Then the viewer opens on that endpoint with the answers I gave
