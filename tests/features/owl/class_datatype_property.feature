Feature: Define a datatype attribute or a relationship on a class

  When adding a property for a class the user chooses a kind — Attribute
  (a datatype property, where the datatype is also chosen) or Relationship
  (an object property). The new property's domain is the class, so it becomes
  available on that class's individuals (and its subclasses).

  Scenario: Choosing Attribute leads to the datatype picker
    When I choose the property kind "attribute"
    Then the picker advances to the datatype step

  Scenario: Choosing Relationship creates an object property
    When I choose the property kind "relationship"
    Then a "ObjectProperty" is created with no range

  Scenario: Choosing a datatype creates a datatype property with that range
    Given the attribute kind was chosen
    When I choose the first datatype
    Then a "DatatypeProperty" is created with an xsd range

  Scenario: A new datatype attribute is available on the class's individuals
    Given a class "Paper" with an individual "MyPaper"
    When I add a datatype attribute "year" to the class
    Then "year" is offered as an applicable property on "MyPaper"
