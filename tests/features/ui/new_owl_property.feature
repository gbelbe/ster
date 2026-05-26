Feature: Create a new OWL property from the Properties section panel

  Scenario: Properties section panel shows the create-property action
    Given a taxonomy with no OWL properties
    When I build the properties section detail panel
    Then the panel contains a "create_owl_property" action field

  Scenario: Create-property action field has the correct key
    Given a taxonomy with no OWL properties
    When I build the properties section detail panel
    Then the action field key is "action:create_owl_property"

  Scenario: Create-property action field carries the right meta type
    Given a taxonomy with no OWL properties
    When I build the properties section detail panel
    Then the action field meta type is "action_add"
