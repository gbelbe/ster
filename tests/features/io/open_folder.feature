Feature: Open ster on a folder
  As someone with RDF files in another folder
  I want to run "ster /path/to/folder"
  So that it behaves exactly as if I had cd'd into that folder and run "ster"

  Scenario: Opening a folder shows the home screen for that folder
    Given a folder "vocab" holding the file "gear.ttl"
    When I run ster with the absolute path of "vocab"
    Then the home screen opens with no file preselected
    And ster is working in "vocab"

  Scenario: A relative folder path works like an absolute one
    Given a folder "vocab" holding the file "gear.ttl"
    When I run ster with the relative path "vocab"
    Then the home screen opens with no file preselected
    And ster is working in "vocab"

  Scenario: A folder with no RDF files behaves like a bare launch there
    Given an empty folder "empty"
    When I run ster with the relative path "empty"
    Then the home screen opens with no file preselected
    And ster is working in "empty"

  Scenario: A path that is neither a folder, an RDF file nor a command is refused clearly
    When I run ster with the relative path "nowhere"
    Then ster stops with an error naming "nowhere"
    And the home screen does not open
