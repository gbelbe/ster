Feature: Full add / edit class modal
  Creating or editing a class collects everything basic in one modal — the URI
  plus an rdfs:label and rdfs:comment for each configured language.

  Scenario: Create a class with a label and a comment
    Given the zoo ontology is open
    When I create a class "Vehicle" with label "Vehicle" and comment "A wheeled thing"
    Then the class "Vehicle" has the label "Vehicle"
    And the class "Vehicle" has the comment "A wheeled thing"

  Scenario: Edit a class — change its label and rename it
    Given the zoo ontology is open
    And a class "Gadget" with label "Gadget"
    When I edit the class "Gadget" renaming it "Widget" with label "Widget"
    Then the class "Widget" has the label "Widget"
    And the class "Gadget" no longer exists
