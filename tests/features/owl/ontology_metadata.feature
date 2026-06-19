Feature: dcterms:title and dcterms:description on owl:Ontology

  Scenario: dcterms:title round-trips through save and reload
    Given a taxonomy with ontology URI "https://ex.org/onto" and dcterms:title "My Ontology"
    When I save and reload the taxonomy
    Then taxonomy.ontology_title is "My Ontology"

  Scenario: dcterms:description round-trips through save and reload
    Given a taxonomy with ontology URI "https://ex.org/onto" and dcterms:description "A description"
    When I save and reload the taxonomy
    Then taxonomy.ontology_description is "A description"

  Scenario: Ontology with only rdfs:label gets dcterms:title pre-filled on load
    Given a taxonomy with ontology URI "https://ex.org/onto" and rdfs:label "Kai" but no dcterms:title
    When I load the taxonomy
    Then taxonomy.ontology_title is "Kai"

  Scenario: Ontology with only rdfs:label gets dcterms:description pre-filled on load
    Given a taxonomy with ontology URI "https://ex.org/onto" and rdfs:label "Kai" but no dcterms:description
    When I load the taxonomy
    Then taxonomy.ontology_description is "Kai"

  Scenario: Ontology overview shows an editable title field
    Given a taxonomy with ontology URI "https://ex.org/onto" and dcterms:title "My Ontology"
    When I build the ontology overview fields
    Then a field with type "ont_title" is present and editable

  Scenario: Ontology overview shows an editable description field
    Given a taxonomy with ontology URI "https://ex.org/onto" and dcterms:description "A description"
    When I build the ontology overview fields
    Then a field with type "ont_description" is present and editable

  Scenario: Title field appears after the label field in the panel
    Given a taxonomy with ontology URI "https://ex.org/onto", rdfs:label "Kai", and dcterms:title "My Ontology"
    When I build the ontology overview fields
    Then the "ont_title" field comes after the "ont_label" field

  Scenario: Description field appears after the title field in the panel
    Given a taxonomy with ontology URI "https://ex.org/onto", dcterms:title "My Ontology", and dcterms:description "A description"
    When I build the ontology overview fields
    Then the "ont_description" field comes after the "ont_title" field

  Scenario: Full descriptive metadata survives a save and reload round-trip
    Given a taxonomy with full descriptive ontology metadata
    When I save and reload the taxonomy
    Then every descriptive metadata field is preserved

  Scenario: An ontology with no extra metadata reloads with empty defaults
    Given a taxonomy with only an ontology URI and no descriptive metadata
    When I save and reload the taxonomy
    Then the optional descriptive metadata fields are empty

  Scenario: Multi-valued metadata round-trips every value
    Given a taxonomy with multiple creators languages and imports
    When I save and reload the taxonomy
    Then all creators languages and imports are preserved
