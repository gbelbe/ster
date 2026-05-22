Feature: AI model picker — local / external split

  Background:
    Given the picker starts at the top level

  # ── Top level ────────────────────────────────────────────────────────────────

  Scenario: Top level shows exactly 3 choices
    Then the picker has 3 items
    And the first item id is "copypaste"
    And the items include id "local"
    And the items include id "external"

  Scenario: Esc at top level closes the picker
    When I press Esc on the picker
    Then the picker signals done

  Scenario: Selecting copy-paste saves and closes
    Given the cursor is on "copypaste"
    When I press Enter on the picker
    Then the picker signals done

  Scenario: Selecting local model switches to local level
    Given the cursor is on "local"
    When I press Enter on the picker
    Then the picker level is "local"
    And the picker is not done

  Scenario: Selecting external model switches to external level
    Given the cursor is on "external"
    When I press Enter on the picker
    Then the picker level is "external"
    And the picker is not done

  # ── Local level ───────────────────────────────────────────────────────────────

  Scenario: Esc at local level returns to top without closing
    Given the picker is at local level
    When I press Esc on the picker
    Then the picker level is "top"
    And the picker is not done

  Scenario: Selecting a detected Ollama model saves the endpoint and closes
    Given the picker is at local level with a detected Ollama model
    When I press Enter on the picker
    Then the picker signals done

  Scenario: Selecting custom local server opens the endpoint form
    Given the picker is at local level with cursor on custom local
    When I press Enter on the picker
    Then the picker level is "endpoint"
    And the picker is not done

  # ── External level ────────────────────────────────────────────────────────────

  Scenario: Esc at external level returns to top without closing
    Given the picker is at external level
    When I press Esc on the picker
    Then the picker level is "top"
    And the picker is not done

  Scenario: Selecting a cloud provider model saves and closes
    Given the picker is at external level with cursor on a keyless model
    When I press Enter on the picker
    Then the picker signals done

  Scenario: Selecting custom external endpoint opens the endpoint form
    Given the picker is at external level with cursor on custom external
    When I press Enter on the picker
    Then the picker level is "endpoint"
    And the picker is not done

  # ── Endpoint form ─────────────────────────────────────────────────────────────

  Scenario: Esc in endpoint form opened from local returns to local
    Given the picker is at endpoint level entered from local
    When I press Esc on the picker
    Then the picker level is "local"
    And the picker is not done

  Scenario: Esc in endpoint form opened from external returns to external
    Given the picker is at endpoint level entered from external
    When I press Esc on the picker
    Then the picker level is "external"
    And the picker is not done

  Scenario: Saving a valid endpoint closes the picker
    Given the picker is at endpoint level with URL and model filled in
    When I press Enter on the picker
    Then the picker signals done

  Scenario: Saving without URL shows a validation error
    Given the picker is at endpoint level with empty URL and model
    When I press Enter on the picker
    Then the picker shows a validation error
    And the picker is not done

  # ── Key prompt (cloud providers) ─────────────────────────────────────────────

  Scenario: Selecting a key-required model opens the key prompt
    Given the picker is at external level with cursor on a key-required model
    When I press Enter on the picker
    Then the picker is in key prompt mode

  Scenario: Submitting an empty API key shows a validation error
    Given the picker is in key prompt mode
    When I press Enter on the picker
    Then the picker shows a validation error

  Scenario: Submitting a valid API key saves and closes
    Given the picker is in key prompt mode with "sk-test" in the buffer
    When I press Enter on the picker
    Then the picker signals done

  Scenario: Esc in the key prompt returns to the model list
    Given the picker is in key prompt mode
    When I press Esc on the picker
    Then the picker is back in list mode
