Feature: Git manager handles KeyboardInterrupt gracefully

  Scenario: Ctrl-C during check_and_pull skips the check silently
    Given a configured GitManager
    When subprocess is interrupted during check_and_pull
    Then check_and_pull returns None without raising

  Scenario: Ctrl-C during pre_edit_check skips it silently
    Given a configured GitManager
    When subprocess is interrupted during pre_edit_check
    Then pre_edit_check returns None without raising

  Scenario: Ctrl-C during fetch_remote skips it silently
    Given a configured GitManager
    When subprocess is interrupted during fetch_remote
    Then fetch_remote returns None without raising
