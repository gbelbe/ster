Feature: Link a concept to an existing OWL class (foaf:focus)
  Promoting a concept can either mint a same-URI class (a pun) or link it to an
  existing OWL class via foaf:focus — the standards-clean SKOS↔OWL bridge. The
  link is non-destructive and reversible, and the class's individuals surface
  under the concept.

  Scenario: Linking a concept to an existing class sets foaf:focus
    Given a taxonomy with a concept "Mammal" and an OWL class "Dog"
    When I link the concept "Mammal" to the class "Dog"
    Then the concept "Mammal" has a foaf:focus link to the class "Dog"
    And "Mammal" is a linked concept, not a pun

  Scenario: The link survives a save and reload
    Given a taxonomy with a concept "Mammal" and an OWL class "Dog"
    When I link the concept "Mammal" to the class "Dog"
    And I save and reload the taxonomy
    Then the concept "Mammal" has a foaf:focus link to the class "Dog"

  Scenario: Unlinking removes the link without deleting the class
    Given a taxonomy with a concept "Mammal" linked to the class "Dog"
    When I unlink the concept "Mammal"
    Then the concept "Mammal" has no foaf:focus link
    And the class "Dog" still exists
