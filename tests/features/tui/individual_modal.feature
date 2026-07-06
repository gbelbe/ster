Feature: Full add / edit individual modal
  Authors create an individual of a class in one modal — its URI, labels and
  comments, plus a value for each property the class (or a superclass) declares.
  Object-property values are picked from the range class's existing individuals.
  The freshly created individual is then revealed and shown so the edit is visible.

  Background:
    Given the zoo ontology is open

  Scenario: Create an individual with a label and a comment
    When I add an individual "Buddy" of "Dog" with label "Buddy" and comment "A good dog"
    Then the individual "Buddy" exists
    And the individual "Buddy" is typed as "Dog"
    And the individual "Buddy" has the label "Buddy"
    And the individual "Buddy" is selected in the tree

  Scenario: The modal suggests inherited properties
    When I open the add-individual modal for "Dog"
    Then the modal offers the property "hasOwner"
    And the modal offers the property "hasAge"

  Scenario: An object-property value is chosen from existing individuals
    When I add an individual "Buddy" of "Dog" with owner "Alice"
    Then the individual "Buddy" has owner "Alice"

  Scenario: Edit an existing individual through the same modal
    When I edit the individual "Rex" renaming it "Rexy" with label "Rexy"
    Then the individual "Rexy" exists
    And the individual "Rex" no longer exists
    And the individual "Rexy" is typed as "Dog"
