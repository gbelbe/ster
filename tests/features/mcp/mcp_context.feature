Feature: Read-only ontology context over MCP
  As someone editing an ontology in ster
  I want my AI agent to see what I am looking at and answer questions about the graph
  So that I can ask about my taxonomy without pasting it into a chat window

  Background:
    Given a zoo taxonomy open in ster

  Scenario: Agent asks what the user is currently looking at
    Given the user has focused the concept "Dog"
    When the agent calls "get_current_context"
    Then the focused entity is labelled "Dog"
    And the ancestor chain is "Animal, Mammal"

  Scenario: Context falls back to the file overview when nothing is focused
    Given no entity is focused
    When the agent calls "get_current_context"
    Then no entity is reported as focused
    And the overview counts 4 concepts

  Scenario: Agent gets oriented with an ontology overview
    When the agent calls "get_overview"
    Then the overview counts 4 concepts

  Scenario: Agent looks up an entity by URI
    When the agent asks for the entity "Mammal"
    Then the entity is labelled "Mammal"
    And its children are "Cat, Dog"

  Scenario: Agent searches for a concept by name
    When the agent searches for "mamm"
    Then the search returns "Mammal"

  Scenario: Agent answers a question with a read-only SPARQL query
    When the agent runs the SPARQL query "SELECT ?s WHERE { ?s a <http://www.w3.org/2002/07/owl#Class> }"
    Then the query returns 1 row

  Scenario: A write query is refused
    When the agent runs the SPARQL query "INSERT DATA { <a> <b> <c> }"
    Then the query is refused as read-only

  Scenario: The agent discovers the available tools
    When the agent lists the tools
    Then the tool list includes "get_current_context"
    And the tool list includes "run_sparql"
