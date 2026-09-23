Feature: The source pane says which file each statement comes from
  As someone reading an entity's RDF with the source pane ("r")
  I want its statements grouped under the name of the file that holds them
  So that I know what my file says, what a context file adds, and what is ster's own commentary

  Background:
    Given a main file "vocab.ttl" defining the concept "ex:Agriculture" with an English label
    And a read-only context file "labels.ttl" adding a French label to "ex:Agriculture"
    And "ex:Policy" in "vocab.ttl" and "ex:Farming" in "labels.ttl" both point to "ex:Agriculture"

  Scenario: The entity's own statements are grouped by file
    When I select "ex:Agriculture" and open the source pane
    Then the "own statements" part has a block for "vocab.ttl" holding the English label
    And it has a block for "labels.ttl" holding the French label

  Scenario: The statements pointing to the entity are grouped by file too
    When I select "ex:Agriculture" and open the source pane
    Then the "point here" part has a block for "vocab.ttl" holding "ex:Policy"
    And it has a block for "labels.ttl" holding "ex:Farming"

  Scenario: The main file comes first, then context files in load order
    When I select "ex:Agriculture" and open the source pane
    Then within each part the "vocab.ttl" block comes before the "labels.ttl" block

  Scenario: A session with only one file still names it
    Given only the main file "vocab.ttl" is loaded
    When I select "ex:Agriculture" and open the source pane
    Then the "own statements" part is a single block, named "vocab.ttl"

  Scenario: A statement both files make is shown once, under the main file
    Given "labels.ttl" also asserts the English label of "ex:Agriculture"
    When I select "ex:Agriculture" and open the source pane
    Then the English label appears only in the "vocab.ttl" block

  Scenario: Only what is in the files is shown as Turtle
    When I select "ex:Agriculture" and open the source pane
    Then no Turtle block contains a part heading, a file name or a count
    And the prefixes are shown once, above every block
    And every block parses as Turtle with those prefixes

  Scenario: Copying takes the Turtle, not ster's headings
    When I select "ex:Agriculture", open the source pane and copy
    Then the clipboard holds every Turtle block and none of the headings
