Feature: The home menu offers the talk-to-graph page once an agent can answer
  The "Connect AI Agent (MCP)" row stays the way to wire a client by hand. When the
  "MCP" plugin is on and an agent or model is usable, the row becomes
  "Agent: talk to graph" and opens the page.

  Scenario: The plugin is off
    Given the "MCP" plugin is off
    And an agent is usable
    When the home menu is built
    Then the menu offers "Connect AI Agent (MCP)"
    And the menu does not offer "Agent: talk to graph"

  Scenario: The plugin is on but no agent is usable
    Given the "MCP" plugin is on
    And no agent is usable
    When the home menu is built
    Then the menu offers "Connect AI Agent (MCP)"
    And the menu does not offer "Agent: talk to graph"

  Scenario: The plugin is on and an agent is usable
    Given the "MCP" plugin is on
    And an agent is usable
    When the home menu is built
    Then the menu offers "Agent: talk to graph"
    And the menu does not offer "Connect AI Agent (MCP)"
    And the "Agent: talk to graph" row is wired to a handler
