Feature: Annotation-property criticity in the config modal
  Every property in the ontology- and entity-metadata catalogs carries a criticity
  (mandatory / important / optional) alongside its include checkbox. The level is
  persisted per property and will later grade warnings/alerts. A property with no
  recorded criticity is treated as optional.

  Scenario: Each catalogued property offers three criticity options defaulting to optional
    Given the config modal is open on a fresh catalog
    Then every ontology-metadata property offers mandatory, important and optional
    And every ontology-metadata property defaults to optional

  Scenario: Setting a property's criticity persists and reloads
    Given the config modal is open on a fresh catalog
    When I set the first ontology-metadata property to mandatory
    Then the saved catalog records that property as mandatory
    And reopening the app loads that property as mandatory

  Scenario: A legacy catalog with no criticity loads as optional
    Given a saved ontology catalog whose entries have no criticity
    When the app loads the ontology catalog
    Then every loaded property is optional

  Scenario: The entity-metadata catalog carries criticity too
    Given the config modal is open on a fresh catalog
    When I set the first entity-metadata property to important
    Then the saved entity catalog records that property as important
