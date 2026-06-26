Feature: Shared fragment-only URI editing
  Adding or renaming any entity reuses a fixed namespace and lets the user edit
  only the local fragment after the configured # or / separator.

  Scenario: A new class is minted under the ontology base
    Given the zoo ontology is open in the New-TUI
    When I add a class with the fragment "Vehicle"
    Then a class "https://example.org/zoo/Vehicle" exists

  Scenario: A new concept is minted under its scheme base
    Given a SKOS taxonomy whose scheme mints under "https://ex.org/wind/"
    When I add a top concept with the fragment "Offshore"
    Then a concept "https://ex.org/wind/Offshore" exists

  Scenario: Renaming an entity locks its own namespace
    Given an entity whose URI is "http://other.org/vocab#Wheel"
    When I rename it changing the fragment to "Axle"
    Then the entity URI becomes "http://other.org/vocab#Axle"
