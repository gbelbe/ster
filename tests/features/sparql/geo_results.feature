Feature: Recognising geographic data in SPARQL results

  Query results are mappable when something in them can be placed on the earth.
  Detection keys off standard WGS84 coordinates alone, so it works for any
  ontology rather than one particular vocabulary.

  Scenario: A query returning entities with coordinates is mappable
    Given a graph where "Brest" has WGS84 coordinates
    When a query returns the entity "Brest"
    Then the result is reported as mappable
    And 1 row is located

  Scenario: A query returning no coordinates is not mappable
    Given a graph where "Brest" has WGS84 coordinates
    When a query returns a row with no entity carrying coordinates
    Then the result is reported as not mappable

  Scenario: Coordinates supplied directly as result columns are recognised
    Given a graph where "Brest" has WGS84 coordinates
    When a query returns bare lat and long columns
    Then the result is reported as mappable
    And 1 row is located

  Scenario: Detection works on an ontology that has nothing to do with boats
    Given a graph of museums where "Louvre" has WGS84 coordinates
    When a query returns the entity "Louvre"
    Then the result is reported as mappable
    And 1 row is located

  Scenario: Rows without coordinates are left unlocated
    Given a graph where "Brest" has WGS84 coordinates and "Nowhere" has none
    When a query returns both entities
    Then the result is reported as mappable
    And 1 row is located
