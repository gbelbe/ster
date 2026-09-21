Feature: Opening the map on the selected entity

  The m shortcut opened the map on the whole file whatever the tree was
  showing, and opened it even for a file holding no geography at all. An empty
  map is not an answer: the reader cannot tell it from one that failed to load.

  Whether an entity "has geography" is read through what it is linked to, not
  only what it carries. A brand holds no coordinates; its stores hold them all.

  Scenario: A file with nothing to place says so instead of opening
    Given a taxonomy with no coordinates
    Then the file reports that nothing can be placed

  Scenario: A file of shapes counts as mappable
    Given a file whose only geography is a region outline
    Then the file reports that something can be placed

  Scenario: A brand reaches the stores that hold the coordinates
    Given a brand two hops from its located stores
    Then the selection resolves to those stores
    And the page is primed with a query over them

  Scenario: An entity with nothing beneath it resolves to nothing
    Given a brand two hops from its located stores
    Then an unrelated entity resolves to nothing
    And no query is built for it
