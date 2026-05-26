Feature: Subject-position hierarchical autocomplete

  Scenario: individuals_by_class bucket maps class to its instances
    Given a taxonomy with class "Animal" and individual "Fido" typed as "Animal"
    When build_uri_index is called
    Then "individuals_by_class" maps "Animal" to "Fido"

  Scenario: Root level any context shows properties
    Given a taxonomy with class "Animal" and property "hasAge"
    When qname_level_candidates is called with any context at root level
    Then the results include "hasAge"

  Scenario: Root level any context does not show typed individuals
    Given a taxonomy with class "Animal" and individual "Fido" typed as "Animal"
    When qname_level_candidates is called with any context at root level
    Then the results do not include "Fido"

  Scenario: Drilling into a class shows its direct subclasses
    Given a taxonomy where "Dog" is a subclass of "Animal"
    When qname_level_candidates is called with any context drilling into "Animal"
    Then the results include "Dog"

  Scenario: Drilling into a class shows its individuals
    Given a taxonomy with class "Animal" and individual "Fido" typed as "Animal"
    When qname_level_candidates is called with any context drilling into "Animal"
    Then the results include "Fido"

  Scenario: Untyped individuals appear at root level
    Given a taxonomy with an individual "Unnamed" with no class
    When qname_level_candidates is called with any context at root level
    Then the results include "Unnamed"
