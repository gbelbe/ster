Feature: An agent shows a query's result in one of ster's views
  As someone asking an AI agent about my ontology
  I want the agent to open the graph, the map or the timeline on a query's result
  So that I can see the answer instead of reading a table of URIs

  The tool goes through ster's own HTTP API, the same endpoints the pages use,
  so it checks a view exactly as the page would draw it. A browser is opened only
  when the agent runs on the same machine as ster; otherwise the agent gets a link.

  Background:
    Given a small ontology with places and dates served by ster

  Scenario: The agent opens the map on places found by a query
    Given the agent runs on the same machine as ster
    When the agent opens the "map" view on a query that finds places
    Then a browser is opened on the map page for that query
    And the agent is told how many places the map shows

  Scenario: The agent opens the timeline on dated things found by a query
    Given the agent runs on the same machine as ster
    When the agent opens the "timeline" view on a query that finds dated things
    Then a browser is opened on the timeline page for that query
    And the agent is told how many moments the timeline shows

  Scenario: The agent opens the graph on a CONSTRUCT query
    Given the agent runs on the same machine as ster
    When the agent opens the "graph" view on a CONSTRUCT query
    Then a browser is opened on the graph page for that query
    And the agent is told how many triples the graph shows

  Scenario: A remote agent gets a link instead of a browser
    Given the agent runs on another machine
    When the agent opens the "map" view on a query that finds places
    Then no browser is opened
    And the agent gets the link to the map page for that query

  Scenario: The agent can ask for the link only
    Given the agent runs on the same machine as ster
    When the agent asks for the link to the "map" view on a query that finds places
    Then no browser is opened
    And the agent gets the link to the map page for that query

  Scenario: A view that would be empty is not opened
    Given the agent runs on the same machine as ster
    When the agent opens the "map" view on a query that finds nothing with a place
    Then no browser is opened
    And the agent is told the map would be empty and why

  Scenario: The graph view refuses a SELECT query with a hint
    When the agent opens the "graph" view on a SELECT query
    Then no browser is opened
    And the agent is told the graph view needs a CONSTRUCT query

  Scenario: A query too long for a link is refused
    When the agent opens the "map" view on a query longer than a link can carry
    Then no browser is opened
    And the agent is told the query is too long for a link
