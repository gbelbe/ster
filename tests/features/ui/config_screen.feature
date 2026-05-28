Feature: Standalone Setup / Options configuration screen
  As a ster user
  I want a dedicated configuration page in the home menu
  So that I can manage server and LLM settings without opening the tree view

  Scenario: Config screen has a Local Server Configuration section
    Given a server configured at URL "http://127.0.0.1" and port 8765
    When I build the config screen fields
    Then a section labelled "Local Server Configuration" is present

  Scenario: Config screen shows the current server URL
    Given a server configured at URL "http://127.0.0.1" and port 8765
    When I build the config screen fields
    Then the Local Server Configuration section contains a field showing "http://127.0.0.1"

  Scenario: Config screen shows the current server port
    Given a server configured at URL "http://127.0.0.1" and port 8765
    When I build the config screen fields
    Then the Local Server Configuration section contains a field showing "8765"

  Scenario: Config screen has a LLM Setup section
    Given a server configured at URL "http://127.0.0.1" and port 8765
    When I build the config screen fields
    Then a section labelled "LLM Setup" is present

  Scenario: Bearer token is hidden by default
    Given a server configured at URL "http://127.0.0.1" and port 8765
    When I build the config screen fields with show_token false
    Then the Local Server Configuration section contains a bearer token field with hidden value

  Scenario: Bearer token is revealed when show_token is true
    Given a server configured at URL "http://127.0.0.1" and port 8765
    When I build the config screen fields with show_token true
    Then the Local Server Configuration section contains a bearer token field with visible value

  Scenario: Restart warning appears after a config change
    Given a server configured at URL "http://127.0.0.1" and port 8765
    When I build the config screen fields with a pending restart
    Then the Local Server Configuration section contains a restart warning field

  Scenario: No restart warning when config is unchanged
    Given a server configured at URL "http://127.0.0.1" and port 8765
    When I build the config screen fields without a pending restart
    Then the Local Server Configuration section contains no restart warning field

  Scenario: Saving a new server URL persists to config
    Given a server configured at URL "http://127.0.0.1" and port 8765
    When the user saves server URL "http://192.168.1.10" via config screen
    Then load_server_config returns URL "http://192.168.1.10"

  Scenario: Saving a new server port persists to config
    Given a server configured at URL "http://127.0.0.1" and port 8765
    When the user saves server port "9999" via config screen
    Then load_server_config returns port 9999
