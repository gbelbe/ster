Feature: Properties section detail panel

  Scenario: Panel shows total property count
    Given an OWL taxonomy with 2 properties
    When I build the properties section fields
    Then a stat field shows count 2

  Scenario: Panel shows data and object property breakdown
    Given an OWL taxonomy with 1 data property and 1 object property
    When I build the properties section fields
    Then a stat field shows data count 1
    And a stat field shows object count 1

  Scenario: Panel shows label coverage at 100 percent
    Given an OWL taxonomy where all 2 properties have labels
    When I build the properties section fields
    Then a stat field shows label coverage 100

  Scenario: Panel shows partial label coverage
    Given an OWL taxonomy where 1 of 2 properties has a label
    When I build the properties section fields
    Then a stat field shows label coverage 50

  Scenario: Panel shows domain coverage
    Given an OWL taxonomy where 1 of 2 properties has a domain
    When I build the properties section fields
    Then a stat field shows domain coverage 50

  Scenario: Panel shows range coverage
    Given an OWL taxonomy where 1 of 2 properties has a range
    When I build the properties section fields
    Then a stat field shows range coverage 50

  Scenario: Each property appears as a selectable navigate_property item
    Given an OWL taxonomy with 2 properties
    When I build the properties section fields
    Then 2 fields have meta type navigate_property
    And each navigate_property field has a uri key in its meta

  Scenario: Property items are sorted alphabetically by label
    Given an OWL taxonomy with properties "zebra" and "apple"
    When I build the properties section fields
    Then the navigate_property items appear in order "apple" then "zebra"

  Scenario: Property items are not editable
    Given an OWL taxonomy with 2 properties
    When I build the properties section fields
    Then all navigate_property fields are not editable

  Scenario: Empty taxonomy returns no navigate_property items and zero count
    Given an OWL taxonomy with no properties
    When I build the properties section fields
    Then 0 fields have meta type navigate_property
    And a stat field shows count 0
