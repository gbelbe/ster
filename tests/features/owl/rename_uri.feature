Feature: OWL URI rename propagated across the taxonomy

  Scenario: Rename a class URI — class exists under new URI only
    Given a taxonomy with OWL class "Dog"
    When I rename class "Dog" to "Canine"
    Then class "Canine" exists in the taxonomy
    And class "Dog" does not exist in the taxonomy

  Scenario: Rename a class URI — subClassOf references are updated
    Given a taxonomy with OWL classes "Animal" and "Dog"
    And "Dog" is a subclass of "Animal"
    When I rename class "Animal" to "LivingThing"
    Then "Dog" subClassOf contains "LivingThing"
    And "Dog" subClassOf does not contain "Animal"

  Scenario: Rename a class URI — equivalentClass and disjointWith are updated
    Given a taxonomy with OWL classes "Cat" and "Dog"
    And "Dog" is equivalent to "Cat"
    And "Dog" is disjoint with "Cat"
    When I rename class "Cat" to "Feline"
    Then "Dog" equivalentClass contains "Feline"
    And "Dog" disjointWith contains "Feline"

  Scenario: Rename a class URI — individual rdf:type references are updated
    Given a taxonomy with OWL class "Dog"
    And an individual "Rex" typed as "Dog"
    When I rename class "Dog" to "Canine"
    Then individual "Rex" is typed as "Canine"
    And individual "Rex" is not typed as "Dog"

  Scenario: Rename a class URI — property domain and range are updated
    Given a taxonomy with OWL class "Dog"
    And a property "hasMaster" with domain "Dog" and range "Dog"
    When I rename class "Dog" to "Canine"
    Then property "hasMaster" domain contains "Canine"
    And property "hasMaster" range contains "Canine"

  Scenario: Rename an individual URI — individual exists under new URI only
    Given a taxonomy with OWL individual "Rex"
    When I rename individual "Rex" to "Max"
    Then individual "Max" exists in the taxonomy
    And individual "Rex" does not exist in the taxonomy

  Scenario: Rename an individual URI — property_values object references are updated
    Given a taxonomy with OWL individuals "Rex" and "Bob"
    And a property "knows" linking "Rex" to "Bob"
    When I rename individual "Bob" to "Alice"
    Then individual "Rex" has a "knows" value of "Alice"
    And individual "Rex" has no "knows" value of "Bob"

  Scenario: Rename a property URI — property exists under new URI only
    Given a taxonomy with OWL property "hasMaster"
    When I rename property "hasMaster" to "ownedBy"
    Then property "ownedBy" exists in the taxonomy
    And property "hasMaster" does not exist in the taxonomy

  Scenario: Rename a property URI — individual property_values predicates are updated
    Given a taxonomy with OWL individual "Rex"
    And a property "hasMaster" linking "Rex" to "Rex"
    When I rename property "hasMaster" to "ownedBy"
    Then individual "Rex" has a property value with predicate "ownedBy"
    And individual "Rex" has no property value with predicate "hasMaster"

  Scenario: Rename fails when the new URI already exists in the taxonomy
    Given a taxonomy with OWL classes "Dog" and "Canine"
    When I rename class "Dog" to "Canine"
    Then a URIAlreadyExistsError is raised

  Scenario: Rename a property URI — individual literal_values predicates are updated
    Given a taxonomy with OWL individual "Rex"
    And individual "Rex" has a literal value with predicate "hasMaster" value "John"
    And property "hasMaster" is added to the taxonomy
    When I rename property "hasMaster" to "ownedBy"
    Then individual "Rex" has a literal value with predicate "ownedBy"
    And individual "Rex" has no literal value with predicate "hasMaster"

  Scenario: Rename an individual URI — literal_values predicates matching old URI are updated
    Given a taxonomy with OWL individual "Rex"
    And individual "Rex" has a literal value with predicate "Rex" value "meta"
    When I rename individual "Rex" to "Max"
    Then individual "Max" has a literal value with predicate "Max"
    And individual "Max" has no literal value with predicate "Rex"

  Scenario: count_owl_uri_references counts literal_values predicate occurrences
    Given a taxonomy with OWL individual "Rex"
    And individual "Rex" has a literal value with predicate "hasMaster" value "John"
    Then counting references to "hasMaster" returns at least 1
