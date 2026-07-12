Feature: OWL individual property capture and display

  # ── Store: URI property capture ───────────────────────────────────────────

  Scenario: URI property pointing to external individual is captured
    Given a taxonomy with individual "Alice" having ObjectProperty "knows" pointing to external URI "https://external.org/Bob"
    When I load the taxonomy from TTL
    Then individual "Alice" has property_value ("knows", "https://external.org/Bob")

  Scenario: Undeclared predicate with URI value is captured
    Given a taxonomy TTL with individual "Doc" having undeclared predicate "seeAlso" pointing to "https://example.org/ref"
    When I load the taxonomy from TTL
    Then individual "Doc" has property_value ("seeAlso", "https://example.org/ref")

  Scenario: rdfs:label is NOT captured in property_values
    Given a taxonomy TTL with individual "Item" having rdfs:label "My Label"
    When I load the taxonomy from TTL
    Then individual "Item" has no property_value with predicate "rdfs:label"

  Scenario: rdf:type is NOT captured in property_values
    Given a taxonomy TTL with individual "Item" typed as class "Thing"
    When I load the taxonomy from TTL
    Then individual "Item" has no property_value with predicate "rdf:type"

  Scenario: schema:url is NOT captured in property_values
    Given a taxonomy TTL with individual "Item" having schema:url "https://example.org"
    When I load the taxonomy from TTL
    Then individual "Item" has no property_value with predicate "schema:url"

  # ── Store: literal value capture ──────────────────────────────────────────

  Scenario: DatatypeProperty literal value is captured
    Given a taxonomy with individual "Report" having DatatypeProperty "title" with literal value "Annual Report"
    When I load the taxonomy from TTL
    Then individual "Report" has literal_value ("title", "Annual Report", "")

  Scenario: Literal lang tag is preserved
    Given a taxonomy with individual "Page" having DatatypeProperty "description" with literal "Hello"@en
    When I load the taxonomy from TTL
    Then individual "Page" has literal_value ("description", "Hello", "@en")

  Scenario: Literal xsd:date datatype is preserved
    Given a taxonomy with individual "Event" having DatatypeProperty "date" with literal "2026-01-01"^^xsd:date
    When I load the taxonomy from TTL
    Then individual "Event" has literal_value ("date", "2026-01-01", "http://www.w3.org/2001/XMLSchema#date")

  # ── Store: round-trip ─────────────────────────────────────────────────────

  Scenario: URI property values round-trip through save and reload
    Given an in-memory taxonomy with individual "A" having property_value ("rel", "https://example.org/B")
    When I save and reload the taxonomy
    Then individual "A" has property_value ("rel", "https://example.org/B")

  Scenario: Literal values round-trip through save and reload
    Given an in-memory taxonomy with individual "A" having literal_value ("note", "hello", "@en")
    When I save and reload the taxonomy
    Then individual "A" has literal_value ("note", "hello", "@en")

  # ── Display: all asserted values shown ───────────────────────────────────

  Scenario: Detail panel shows asserted URI value regardless of domain matching
    Given a taxonomy with individual "Inst" of class "ClassA" having property "rel" with domain "ClassB" pointing to individual "Target"
    When I build the individual detail for "Inst"
    Then the detail panel contains a property row for "rel" with value "Target"

  Scenario: Detail panel shows external URI value as raw string
    Given a taxonomy with individual "Inst" having property "rel" pointing to external URI "https://external.org/X"
    When I build the individual detail for "Inst"
    Then the detail panel contains a property row for "rel" with value "https://external.org/X"

  Scenario: Detail panel shows literal values
    Given a taxonomy with individual "Inst" having literal_value ("score", "42", "")
    When I build the individual detail for "Inst"
    Then the detail panel contains a property row for "score" with value "42"

  # ── Display: only asserted values (no applicable-but-unapplied placeholders) ──

  Scenario: An applicable property with no asserted value is not shown
    Given a taxonomy with individual "Doc" of class "Document" with applicable property "hasAuthor" and no asserted value
    When I build the individual detail for "Doc"
    Then the detail panel does not contain an empty placeholder row for "hasAuthor"

  Scenario: An asserted property value is shown as an editable row
    Given a taxonomy with individual "Doc" of class "Document" having property "hasAuthor" pointing to individual "Alice"
    When I build the individual detail for "Doc"
    Then the detail panel contains a property row for "hasAuthor" with value "Alice"
    And the detail panel does not contain an empty placeholder row for "hasAuthor"

  # ── Display: schema.org add actions conditional ───────────────────────────

  Scenario: Add schema:url action hidden when schema:url already present
    Given a taxonomy with individual "Item" having schema:url "https://example.org"
    When I build the individual detail for "Item"
    Then the detail panel does not contain an "add_schema_url" action

  Scenario: Add schema:image action shown when no schema:image present
    Given a taxonomy with individual "Item" having no schema:image
    When I build the individual detail for "Item"
    Then the detail panel contains an "add_schema_image" action
