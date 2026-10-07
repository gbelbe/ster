Feature: The MCP plugin can be switched from the command line
  Recording agents' queries and Talk to graph are one plugin, normally chosen in
  Config > Plugins. A launch can force it for one run without changing that choice.

  Background:
    Given the saved plugin choices are the defaults

  Scenario: ster serve --mcp records traces and offers Talk to graph
    When ster serve is launched on a file with "--mcp"
    Then the MCP plugin is on for that run
    And the saved choice is still off

  Scenario: ster serve --no-mcp turns off a plugin that was saved on
    Given the MCP plugin is saved as on
    When ster serve is launched on a file with "--no-mcp"
    Then the MCP plugin is off for that run
    And the saved choice is still on

  Scenario: Without the option the saved choice applies
    Given the MCP plugin is saved as on
    When ster serve is launched on a file without the option
    Then the MCP plugin is on for that run

  Scenario: The viewer takes the same option
    When ster show is launched on a file with "--mcp"
    Then the MCP plugin is on for that run

  Scenario: The environment does the same for every command
    Given the environment says STER_PLUGIN_MCP is "1"
    Then the MCP plugin is on for that run

  Scenario: A choice made in Config replaces the launch option
    When ster serve is launched on a file with "--mcp"
    And the person unticks MCP in Config
    Then the MCP plugin is off for that run

  Scenario: A server started with the option records its queries
    When ster serve is launched on a file with "--mcp"
    Then a server built for that file records traces beside it
