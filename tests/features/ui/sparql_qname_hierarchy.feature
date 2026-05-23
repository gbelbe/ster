Feature: Hierarchical class navigation in SPARQL QName popup

  Background:
    Given a taxonomy with namespace "kai" and a three-level class tree: Thing at root, Digital child of Thing, AnalogDevice at root, Switch child of Digital

  Scenario: root-level classes are those with no parent in the same namespace
    Then "Thing" appears in the "roots" bucket for "kai"
    And "AnalogDevice" appears in the "roots" bucket for "kai"
    And "Digital" does not appear in the "roots" bucket for "kai"
    And "Switch" does not appear in the "roots" bucket for "kai"

  Scenario: children map records direct subclass relationships
    Then the children of "Thing" in "kai" contains "Digital"
    And the children of "Digital" in "kai" contains "Switch"

  Scenario: leaf class has no entry in children map
    Then "AnalogDevice" has no children in "kai"
    And "Switch" has no children in "kai"

  Scenario: level candidates at root return root classes
    When level candidates are requested for prefix "kai" at root with filter ""
    Then the candidates include "Thing" and "AnalogDevice"
    And "Digital" is not in the candidates
    And "Switch" is not in the candidates

  Scenario: level candidates at a parent return its direct children only
    When level candidates are requested for prefix "kai" under parent "Thing" with filter ""
    Then the candidates include "Digital"
    And "Thing" is not in the candidates
    And "Switch" is not in the candidates

  Scenario: classes with children are flagged has_children=True
    When level candidates are requested for prefix "kai" at root with filter ""
    Then "Thing" is flagged has_children=True
    And "AnalogDevice" is flagged has_children=False

  Scenario: filter is applied at each level
    When level candidates are requested for prefix "kai" at root with filter "An"
    Then the candidates include "AnalogDevice"
    And "Thing" is not in the candidates
