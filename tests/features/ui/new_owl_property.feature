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

  Scenario: Committing new_owl_property_uri creates the property in the taxonomy
    Given a taxonomy with ontology URI "https://ex.org/onto"
    When I commit a new_owl_property_uri field with value "https://ex.org/onto#hasMaster"
    Then the taxonomy contains property "https://ex.org/onto#hasMaster"

  Scenario: Committing new_owl_class_property_uri creates a property with domain
    Given a taxonomy with OWL class "https://ex.org/onto#Dog"
    When I commit a new_owl_class_property_uri field with value "https://ex.org/onto#hasMaster" and class_uri "https://ex.org/onto#Dog"
    Then the taxonomy contains property "https://ex.org/onto#hasMaster"
    And property "https://ex.org/onto#hasMaster" has domain "https://ex.org/onto#Dog"
