Feature: Edit the ontology domain and prefix with propagation and counts

  The base URI's domain (host) can be changed on its own — the path and
  separator are kept and every local entity URI is rebased, reporting how many
  changed. The prefix (namespace label) can be renamed independently: entity
  identities stay the same, only the abbreviation changes, reporting how many
  terms use it.

  Background:
    Given an ontology based at "https://www.adeo.com/ontology/kai" with prefix "kai" and 4 local entities

  Scenario: Changing the domain swaps only the host
    When I change the ontology domain to "kai.adeo.com"
    Then the ontology URI is "https://kai.adeo.com/ontology/kai"
    And all 4 local entities are under "https://kai.adeo.com/ontology/kai#"

  Scenario: Counting a domain change reports all affected entities
    When I count changes for a domain change to "kai.adeo.com"
    Then the change count is 4

  Scenario: An unchanged domain reports zero changes
    When I count changes for a domain change to "www.adeo.com"
    Then the change count is 0

  Scenario: Renaming the prefix keeps entity identities and reports the count
    When I rename the prefix "kai" to "adeo"
    Then the prefix bound to the ontology is "adeo"
    And the entity URIs are unchanged
    And the prefix rename count is 4
