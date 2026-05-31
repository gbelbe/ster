Feature: Live refresh via SSE
  As a user of the graph view
  I want the graph to update automatically when the ontology file changes
  So that edits made in the ster CLI are immediately reflected in the browser

  Background:
    Given the API server is running with the Animal/Dog/Tool ontology

  Scenario: GET /api/graph returns graph data with nodes and edges
    When I GET /api/graph
    Then the response status is 200
    And the response contains a "nodes" list
    And the response contains an "edges" list

  Scenario: GET /api/events returns SSE content type
    When I GET /api/events with the token as query param
    Then the response status is 200
    And the Content-Type header contains "text/event-stream"

  Scenario: SSE broadcaster emits updated event to all listeners
    Given an SSE broadcaster with one connected listener
    When the broadcaster is notified of a change
    Then the listener receives an "updated" event

  Scenario: POST /api/individuals notifies the SSE broadcaster
    Given a broadcaster spy is active
    When I POST /api/individuals with class "Dog" and label "Fido"
    Then the broadcaster was notified once
