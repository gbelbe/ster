Feature: Server setup UI in the global overview panel
  As a ster user
  I want to configure the server and LLM from the global overview panel
  So that everything is discoverable in one place

  Background:
    Given a workspace with a single taxonomy

  Scenario: Server Setup section is present
    When I build the global overview fields
    Then a section labelled "Server Setup" is present

  Scenario: Server URL field shows the default
    When I build the global overview fields
    Then the Server Setup section contains a field showing "http://127.0.0.1"

  Scenario: Port field shows the default
    When I build the global overview fields
    Then the Server Setup section contains a field showing "8765"

  Scenario: Bearer token field is present
    When I build the global overview fields
    Then the Server Setup section contains a field labelled "bearer token"

  Scenario: LLM Setup section is present
    When I build the global overview fields
    Then a section labelled "LLM Setup" is present

  Scenario: Language picker is in LLM Setup section
    When I build the global overview fields
    Then the LLM Setup section contains a field with action "pick_lang"

  Scenario: AI config action is in LLM Setup section
    When I build the global overview fields
    Then the LLM Setup section contains a field with action "open_ai_config"

  Scenario: No bare "Setup" section remains
    When I build the global overview fields
    Then no section is labelled exactly "Setup"

  Scenario: Restart warning shown when config change is pending
    When I build the global overview fields with a pending restart
    Then the Server Setup section contains a restart warning field

  Scenario: No restart warning when config is unchanged
    When I build the global overview fields
    Then the Server Setup section contains no restart warning field
