Feature: The source pane shows where each statement is in its file
  As someone who reads an entity in the source pane ("r") and then fixes it in the file
  I want each statement's line number, and which files use each prefix
  So that I can go straight to the right place in the right file

  Background:
    Given a main file "vocab.ttl" whose statement about "ex:Farm" starts on line 4
    And a read-only context file "links.ttl" whose statement pointing to "ex:Farm" starts on line 5

  Scenario: Each statement shows the line where it starts in its file
    When I select "ex:Farm" and open the source pane
    Then the "vocab.ttl" block marks "ex:Farm" with "L4"
    And the "links.ttl" block marks "ex:Elsewhere" with "L5"

  Scenario: Each prefix names the files that use it, most shared first
    When I select "ex:Farm" and open the source pane
    Then the first prefix is "ex:", used by "vocab.ttl, links.ttl"
    And the prefix "rdfs:" is used by "links.ttl"

  Scenario: Line numbers and prefix files are not part of the copied Turtle
    When I select "ex:Farm", open the source pane and copy
    Then the clipboard holds no line number and no file note
