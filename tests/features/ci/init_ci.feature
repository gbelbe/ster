Feature: ster init-ci command

  Scenario: Scaffolds workflow and config in a fresh project
    Given an empty project directory
    When I run "ster init-ci"
    Then ".github/workflows/taxonomy-ci.yml" is created
    And "onto-ci.yml" is created

  Scenario: Skips onto-ci.yml when --no-config is set
    Given an empty project directory
    When I run "ster init-ci --no-config"
    Then ".github/workflows/taxonomy-ci.yml" is created
    And "onto-ci.yml" does not exist

  Scenario: Warns and skips when workflow already exists
    Given a project with an existing "taxonomy-ci.yml"
    When I run "ster init-ci"
    Then the exit code is 0
    And the output contains "already exists"

  Scenario: --force overwrites existing workflow
    Given a project with an existing "taxonomy-ci.yml"
    When I run "ster init-ci --force"
    Then ".github/workflows/taxonomy-ci.yml" is created

  Scenario: Prompts to add CI on startup when no CI workflow exists
    Given a git project directory with ontology files but no CI workflow at all
    And the user will confirm the CI prompt
    When ster checks for CI on startup
    Then ".github/workflows/taxonomy-ci.yml" is created

  Scenario: User declines prompt — no file is created
    Given a git project directory with ontology files but no CI workflow at all
    And the user will decline the CI prompt
    When ster checks for CI on startup
    Then ".github/workflows/taxonomy-ci.yml" does not exist

  Scenario: No prompt when another CI workflow already exists
    Given a git project directory with ontology files and an existing CI workflow
    When ster checks for CI on startup
    Then ".github/workflows/taxonomy-ci.yml" does not exist
