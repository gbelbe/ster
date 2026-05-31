Feature: Individual property value picker respects property range

  Background:
    Given a taxonomy with classes "Dog" and "Person"
    And individuals "Rex" typed as "Dog" and "Alice" typed as "Person"

  Scenario: Picker is filtered to range class when property has a range
    Given a property "hasMaster" with range "Person"
    When I build individual candidates for "hasMaster" excluding "Rex"
    Then "Alice" appears in the candidates
    And "Rex" does not appear in the candidates

  Scenario: Picker shows all classes when property has no range
    Given a property "hasMaster" with no range
    When I build individual candidates for "hasMaster" excluding "Rex"
    Then "Alice" appears in the candidates

  Scenario: Range filtering includes individuals typed as subclasses of range
    Given a class "Puppy" that is a subclass of "Dog"
    And individual "Tiny" typed as "Puppy"
    And a property "hasPet" with range "Dog"
    When I build individual candidates for "hasPet" excluding no one
    Then "Rex" appears in the candidates
    And "Tiny" appears in the candidates
    And "Alice" does not appear in the candidates

  Scenario: Picker excludes the source individual from candidates
    Given a property "hasMaster" with range "Person"
    When I build individual candidates for "hasMaster" excluding "Alice"
    Then "Alice" does not appear in the candidates
