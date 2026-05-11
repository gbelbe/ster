Feature: OWL class property management from the class detail panel

  Scenario: Direct properties appear in the class detail panel
    Given a taxonomy with class "Person" having property "hasName" with domain "Person"
    When I build the class detail for "Person"
    Then the detail panel contains a "Properties" section
    And "hasName" appears as a direct property row

  Scenario: Class with no properties shows only the add-property action
    Given a taxonomy with class "Animal" and no properties
    When I build the class detail for "Animal"
    Then the detail panel contains a "Properties" section
    And the detail panel contains an "add_class_property" action row

  Scenario: Inherited properties appear non-editable with parent label
    Given a taxonomy with class "Employee" subClassOf "Person"
    And class "Person" has property "hasName" with domain "Person"
    When I build the class detail for "Employee"
    Then the detail panel shows "hasName" as inherited from "Person"
    And the inherited row has no edit action

  Scenario: Multi-level inheritance collects all ancestor properties
    Given a 3-level class hierarchy with "Manager" under "Employee" under "Person"
    And "Person" has class property "hasName" and "Employee" has class property "hasRole"
    When I build the class detail for "Manager"
    Then the detail panel shows "hasName" as inherited from "Person"
    And the detail panel shows "hasRole" as inherited from "Employee"

  Scenario: No duplicate inherited properties across diamond inheritance
    Given a taxonomy with classes "C" "A" "B" "Base"
    And "A" subClassOf "Base" and "B" subClassOf "Base"
    And "C" subClassOf "A" and "C" subClassOf "B"
    And class "Base" has property "baseP"
    When I build the class detail for "C"
    Then "baseP" appears only once as an inherited property row

  Scenario: Direct properties are not repeated in the inherited section
    Given a taxonomy with class "Child" subClassOf "Parent"
    And class "Parent" has property "sharedP"
    And class "Child" also has property "sharedP" as a direct domain
    When I build the class detail for "Child"
    Then "sharedP" appears as a direct property row
    And "sharedP" does not appear as an inherited property row

  Scenario: Add new property from class detail panel
    Given a taxonomy with class "Animal" and no properties
    When I invoke add_owl_property with uri "hasAge" label "hasAge" domain "Animal"
    Then a new OWLProperty "hasAge" exists in the taxonomy
    And its domain is "Animal"

  Scenario: Add property with explicit range
    Given a taxonomy with class "Animal" and class "Food"
    When I invoke add_owl_property with uri "eats" label "eats" domain "Animal" range "Food"
    Then the property "eats" has domain "Animal" and range "Food"

  Scenario: Adding property with duplicate URI raises an error
    Given a taxonomy with property "hasName" already declared
    When I invoke add_owl_property with uri "hasName" label "hasName" domain "Animal"
    Then a ValueError is raised

  Scenario: Delete property with no impacted individuals
    Given a taxonomy with property "hasColor" and no individuals using it
    When I invoke delete_owl_property for "hasColor"
    Then the property is removed from the taxonomy
    And the returned impacted list is empty

  Scenario: Delete property with impacted individuals returns their URIs
    Given a taxonomy with property "hasColor"
    And individual "RedCar" has a value for property "hasColor"
    When I invoke delete_owl_property for "hasColor"
    Then the property is removed from the taxonomy
    And the returned impacted list contains "RedCar"

  Scenario: Clear property values removes tuples from individuals
    Given a taxonomy with property "hasColor"
    And individual "RedCar" has a value for property "hasColor"
    And individual "BlueBike" has a value for property "hasColor"
    When I invoke clear_property_values for "hasColor"
    Then "RedCar" has no property values for "hasColor"
    And "BlueBike" has no property values for "hasColor"

  Scenario: Clear property values leaves other property values untouched
    Given a taxonomy with properties "hasColor" and "hasSize"
    And individual "RedCar" has values for both "hasColor" and "hasSize"
    When I invoke clear_property_values for "hasColor"
    Then "RedCar" still has a property value for "hasSize"
