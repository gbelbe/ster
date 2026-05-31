Feature: Rename the global ontology base URI with entity propagation

  Scenario: Renaming the ontology URI updates taxonomy.ontology_uri
    Given a taxonomy with ontology URI "https://example.org/onto" and a class "Dog"
    When I rename the ontology URI to "https://example.org/animals" with separator "#"
    Then the taxonomy ontology URI is "https://example.org/animals"

  Scenario: All local class URIs are updated to the new base
    Given a taxonomy with ontology URI "https://example.org/onto" and a class "Dog"
    When I rename the ontology URI to "https://example.org/animals" with separator "#"
    Then class "https://example.org/animals#Dog" exists in the taxonomy
    And class "https://example.org/onto#Dog" does not exist in the taxonomy

  Scenario: Individual and property URIs using the old base are updated
    Given a taxonomy with ontology URI "https://example.org/onto" and a class "Dog"
    And an individual "https://example.org/onto#Rex" typed as "https://example.org/onto#Dog"
    And a property "https://example.org/onto#hasMaster" with domain "https://example.org/onto#Dog"
    When I rename the ontology URI to "https://example.org/animals" with separator "#"
    Then individual "https://example.org/animals#Rex" exists in the taxonomy
    And property "https://example.org/animals#hasMaster" exists in the taxonomy

  Scenario: External URIs from other namespaces are not touched
    Given a taxonomy with ontology URI "https://example.org/onto" and a class "Dog"
    And the class "https://example.org/onto#Dog" has a subclass link to "https://external.org/Animal"
    When I rename the ontology URI to "https://example.org/animals" with separator "#"
    Then "https://example.org/animals#Dog" still references "https://external.org/Animal"

  Scenario: The separator can change from hash to slash
    Given a taxonomy with ontology URI "https://example.org/onto" using "#" and a class "Dog"
    When I rename the ontology URI to "https://example.org/onto" with separator "/"
    Then class "https://example.org/onto/Dog" exists in the taxonomy
    And class "https://example.org/onto#Dog" does not exist in the taxonomy

  Scenario: The separator can change from slash to hash
    Given a taxonomy with ontology URI "https://example.org/onto" using "/" and a class "Dog"
    When I rename the ontology URI to "https://example.org/onto" with separator "#"
    Then class "https://example.org/onto#Dog" exists in the taxonomy
    And class "https://example.org/onto/Dog" does not exist in the taxonomy

  Scenario: Cross-references between local entities are updated
    Given a taxonomy with ontology URI "https://example.org/onto" and two classes "Animal" and "Dog"
    And "https://example.org/onto#Dog" is a subclass of "https://example.org/onto#Animal"
    When I rename the ontology URI to "https://example.org/animals" with separator "#"
    Then "https://example.org/animals#Dog" is a subclass of "https://example.org/animals#Animal"

  Scenario: Entities whose URI does not match the base are not touched
    Given a taxonomy with ontology URI "https://example.org/onto" and a class "Dog"
    And a class "https://other.org/Cat" exists independently
    When I rename the ontology URI to "https://example.org/animals" with separator "#"
    Then class "https://other.org/Cat" still exists in the taxonomy

  Scenario: Counting URI changes for separator-only change counts all local entities
    Given a taxonomy with ontology URI "https://example.org/onto" using "/" and a class "Dog"
    And an individual "https://example.org/onto/Rex" typed as "https://example.org/onto/Dog"
    When I count URI changes renaming to "https://example.org/onto" with separator "#"
    Then the change count is 2
    And the old base is "https://example.org/onto/"
    And the new base is "https://example.org/onto#"

  Scenario: Counting URI changes when nothing changes returns zero
    Given a taxonomy with ontology URI "https://example.org/onto" using "#" and a class "Dog"
    When I count URI changes renaming to "https://example.org/onto" with separator "#"
    Then the change count is 0

  Scenario: Counting URI changes for a URI rename counts all local entities
    Given a taxonomy with ontology URI "https://example.org/onto" and a class "Dog"
    And a property "https://example.org/onto#hasMaster" with domain "https://example.org/onto#Dog"
    When I count URI changes renaming to "https://example.org/animals" with separator "#"
    Then the change count is 2

  Scenario: Counting URI changes does not count external URIs
    Given a taxonomy with ontology URI "https://example.org/onto" and a class "Dog"
    And a class "https://external.org/Animal" exists independently
    When I count URI changes renaming to "https://example.org/animals" with separator "#"
    Then the change count is 1
