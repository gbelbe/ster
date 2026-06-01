Feature: SKOS concept URI rename propagated across mapping properties

  When a concept URI is renamed, every cross-reference to it must be updated —
  including the SKOS mapping properties (broadMatch, narrowMatch, relatedMatch,
  exactMatch, closeMatch) on other concepts. URIs that are not being renamed
  must be left untouched.

  Scenario: Rename a concept URI — broadMatch references are updated
    Given a taxonomy with concepts "Animal" and "Dog"
    And "Dog" has broadMatch "Animal"
    When I rename concept "Animal" to "LivingThing"
    Then "Dog" broadMatch contains "LivingThing"
    And "Dog" broadMatch does not contain "Animal"

  Scenario: Rename a concept URI — narrowMatch references are updated
    Given a taxonomy with concepts "Animal" and "Dog"
    And "Animal" has narrowMatch "Dog"
    When I rename concept "Dog" to "Canine"
    Then "Animal" narrowMatch contains "Canine"
    And "Animal" narrowMatch does not contain "Dog"

  Scenario: Rename a concept URI — relatedMatch references are updated
    Given a taxonomy with concepts "Cat" and "Dog"
    And "Dog" has relatedMatch "Cat"
    When I rename concept "Cat" to "Feline"
    Then "Dog" relatedMatch contains "Feline"
    And "Dog" relatedMatch does not contain "Cat"

  Scenario: Rename a concept URI — exactMatch references are updated
    Given a taxonomy with concepts "Cat" and "Dog"
    And "Dog" has exactMatch "Cat"
    When I rename concept "Cat" to "Feline"
    Then "Dog" exactMatch contains "Feline"
    And "Dog" exactMatch does not contain "Cat"

  Scenario: Rename a concept URI — closeMatch references are updated
    Given a taxonomy with concepts "Cat" and "Dog"
    And "Dog" has closeMatch "Cat"
    When I rename concept "Cat" to "Feline"
    Then "Dog" closeMatch contains "Feline"
    And "Dog" closeMatch does not contain "Cat"

  Scenario: Rename a concept URI — unrelated mapping targets are left untouched
    Given a taxonomy with concepts "Cat" and "Dog"
    And "Dog" has exactMatch "Cat"
    And "Dog" has an external exactMatch "https://other.org/vocab#Wolf"
    When I rename concept "Cat" to "Feline"
    Then "Dog" exactMatch contains the external URI "https://other.org/vocab#Wolf"
