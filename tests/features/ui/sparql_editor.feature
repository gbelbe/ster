Feature: SPARQL editor smart completions

  # ── Prefix header ─────────────────────────────────────────────────────────────

  Scenario: Prefix header always includes standard prefixes
    Given an empty taxonomy
    When I build the prefix header
    Then the header declares "PREFIX rdf:"
    And the header declares "PREFIX rdfs:"
    And the header declares "PREFIX owl:"
    And the header declares "PREFIX skos:"

  Scenario: Prefix header includes custom namespace bindings from the taxonomy
    Given a taxonomy with kai namespace binding
    When I build the prefix header
    Then the header declares "PREFIX kai:"

  Scenario: Prefix header never duplicates a PREFIX declaration
    Given a taxonomy that redeclares the rdf namespace
    When I build the prefix header
    Then the header contains exactly one "PREFIX rdf:"

  # ── QName index ───────────────────────────────────────────────────────────────

  Scenario: QName index includes class local names under the matching prefix
    Given a taxonomy with kai namespace binding
    And a class with URI "https://ex.org/kai/Digital"
    When I build the QName index
    Then "Digital" appears in the "kai" prefix candidates

  Scenario: QName index always includes well-known skos local names
    Given an empty taxonomy
    When I build the QName index
    Then "prefLabel" appears in the "skos" prefix candidates
    And "broader" appears in the "skos" prefix candidates

  # ── Bracket auto-close ────────────────────────────────────────────────────────

  Scenario: Typing brace expands to an indented block with cursor inside
    Given a SPARQL buffer "WHERE " with cursor at the end
    When the user types "{"
    Then the buffer contains a brace block
    And the cursor is positioned inside the block

  # ── Clause keyword expansion ──────────────────────────────────────────────────

  Scenario: Selecting WHERE from the keyword popup expands to a brace block
    Given a query state with buffer "WH"
    When the user inserts keyword "WHERE"
    Then the buffer contains a brace block
    And the cursor is positioned inside the block
