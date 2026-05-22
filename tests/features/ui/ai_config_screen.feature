Feature: AI model configuration wizard

  Scenario: Wizard starts in mode selection step when llm is available
    Given the llm package is available
    When an AI config wizard is created
    Then the wizard state step is "mode"

  Scenario: LLM not installed shows install prompt
    Given the llm package is not available
    When an AI config wizard is created
    Then the wizard is in the install state

  Scenario: Pressing Esc at mode step closes the wizard
    Given a wizard at the "mode" step
    When I press Esc on the wizard
    Then the wizard on_key returns done

  Scenario: Selecting copy-paste mode saves preference and completes wizard
    Given a wizard at the "mode" step with copy-paste as only option
    When I press Enter on the wizard
    Then the wizard state step is "done"
    And the wizard mode is "copypaste"

  Scenario: Selecting online mode advances to provider list
    Given a wizard at the "mode" step with an online provider
    When I press Enter on the wizard
    Then the wizard state step is "provider"
    And the wizard mode is "online"

  Scenario: Provider Esc returns to mode step
    Given a wizard at the "provider" step
    When I press Esc on the wizard
    Then the wizard state step is "mode"

  Scenario: Selecting a provider advances to model step
    Given a wizard at the "provider" step with one provider
    When I press Enter on the wizard
    Then the wizard state step is "model"

  Scenario: Selecting a model without API key saves it and completes
    Given a wizard at the "model" step with a keyless model
    When I press Enter on the wizard
    Then the wizard state step is "done"

  Scenario: Selecting a model with API key advances to key entry
    Given a wizard at the "model" step with a key-required model
    When I press Enter on the wizard
    Then the wizard state step is "key"

  Scenario: Pressing Esc at key step saves model without key and completes
    Given a wizard at the "key" step for model "claude-3-opus"
    When I press Esc on the wizard
    Then the wizard state step is "done"

  Scenario: Entering a valid API key saves it and completes setup
    Given a wizard at the "key" step for model "claude-3-opus"
    And the key buffer contains "sk-test-123"
    When I press Enter on the wizard
    Then the wizard state step is "done"

  Scenario: Enter with empty key buffer shows validation error
    Given a wizard at the "key" step for model "claude-3-opus"
    When I press Enter on the wizard
    Then the wizard shows an error
