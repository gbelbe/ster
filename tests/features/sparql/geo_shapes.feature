Feature: Map polygons and collections, not only points
  ster places a result row when it can find coordinates for it. Real geographic
  ontologies publish more than points: a région is a polygon, a country with
  islands a multipolygon. Those are published under GeoSPARQL, whose literals
  carry their own datatype — so the geometry can be recognised without ster
  knowing the predicate that holds it.

  Scenario: A polygon published as a WKT literal is mapped
    Given an entity whose geometry is a GeoSPARQL WKT polygon
    When ster resolves its geometry
    Then it is mapped as a Polygon

  Scenario: A geometry is recognised under an unknown predicate
    Given an entity whose polygon hangs off a predicate ster has never seen
    When ster resolves its geometry
    Then it is mapped as a Polygon

  Scenario: A GeoJSON literal is mapped
    Given an entity whose geometry is a GeoSPARQL GeoJSON multipolygon
    When ster resolves its geometry
    Then it is mapped as a MultiPolygon

  Scenario: The ontology chooses between several geometries
    Given an entity carrying both a point and a polygon
    And the point is marked as its default geometry
    When ster resolves its geometry
    Then it is mapped as a Point

  Scenario: Coordinates still work when there is no geometry
    Given an entity carrying only wgs84 latitude and longitude
    When ster resolves its geometry
    Then it is mapped as a Point

  Scenario: A shape can still be clustered
    Given an entity whose geometry is a GeoSPARQL WKT polygon
    When ster resolves its geometry
    Then it reports a centroid so it can be grouped with points

  Scenario: An unknown coordinate reference system is refused, not guessed
    Given an entity whose WKT literal declares a projected coordinate system
    When ster resolves its geometry
    Then nothing is mapped for it
