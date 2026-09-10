Feature: A file ster cannot model never opens as an empty tree

  ster builds its model by looking subjects up by their rdf:type against a
  vocabulary it knows — skos:Concept, owl:Class, the OWL property types, and
  anything typed with a class the file itself declares. A file that types its
  subjects with a class it never declares matches none of that, so every triple
  falls through to residue and the taxonomy comes out empty.

  Opening that as a blank tree is the worst possible answer: nothing is wrong
  with the file that ster can see, and nothing on screen says so. The load has
  to stop, say which type it did not recognise, and offer to declare it.

  Background:
    Given a capability file whose subjects are all typed "ex:BusinessCapability"
    And that type is never declared as a class

  Scenario: The browser refuses to open on an empty model
    When I open the capability file in the browser
    Then the tree is not shown
    And I am told that no entity was recognised
    And I am told "ex:BusinessCapability" is used 3 times and never declared

  Scenario: Declaring the missing type brings the entities back
    Given the unreadable-file modal is open on the capability file
    When I choose to declare the missing types
    Then the declaration is written through the service
    And the browser shows 3 individuals

  Scenario: Opening anyway is still possible
    Given the unreadable-file modal is open on the capability file
    When I choose to open the file anyway
    Then the browser opens with an empty tree
    And the file on disk is unchanged

  Scenario: A file with no triples at all
    Given an empty Turtle file
    When I open the empty file in the browser
    Then I am told the file contains no triples
    And no fix is offered

  Scenario: The CLI reports the same problem
    When I run "show --plain" on the capability file
    Then the output names "ex:BusinessCapability"
    And the output prints the declaration to add
    And the exit code is not zero

  Scenario: A readable file opens as it always did
    Given a normal SKOS taxonomy file
    When I open the normal file in the browser
    Then no unreadable-file modal appears
