Feature: Editing the ontology in the New-TUI
  As a curator I can create, rename, re-link and delete OWL classes and
  individuals from the detail panel. Every change is validated by the core and
  written back to the .ttl, so the file stays consistent.

  # Phase 1 — OWL classes

  Scenario: Rename a class everywhere
    Given the zoo ontology is open for editing
    When I rename the class "Cat" to "Feline"
    Then the class "Feline" exists
    And the class "Cat" no longer exists

  Scenario: Edit a class label
    Given the zoo ontology is open for editing
    When I set the label of the class "Cat" to "Kitty"
    Then the class "Cat" has the label "Kitty"

  Scenario: Add a subclass
    Given the zoo ontology is open for editing
    When I add a subclass "Kitten" under the class "Cat"
    Then the class "Kitten" exists

  Scenario: Add a superclass (polyhierarchy)
    Given the zoo ontology is open for editing
    When I add the superclass "Person" to the class "Cat"
    Then the class "Cat" is a subclass of "Person"

  # (Remove-superclass had no home once the class Hierarchy section was removed.)

  Scenario: Delete a class
    Given the zoo ontology is open for editing
    When I delete the class "Cat" choosing "delete_all"
    Then the class "Cat" no longer exists

  # Phase 2 — OWL individuals

  Scenario: Create an individual of a class
    Given the zoo ontology is open for editing
    When I add an individual "Mimi" of the class "Cat"
    Then the individual "Mimi" exists

  Scenario: Add a class membership to an individual
    Given the zoo ontology is open for editing
    When I add the type "Cat" to the individual "Rex"
    Then the individual "Rex" has type "Cat"

  Scenario: Remove a class membership from an individual
    Given the zoo ontology is open for editing
    When I remove the type "Dog" from the individual "Rex"
    Then the individual "Rex" does not have type "Dog"

  Scenario: Delete an individual
    Given the zoo ontology is open for editing
    When I delete the individual "Rex"
    Then the individual "Rex" no longer exists

  # Phase 3 — ontology overview (the global window)

  Scenario: Set the ontology title from the overview
    Given the zoo ontology is open for editing
    When I set the ontology title to "Zoo Ontology"
    Then the ontology overview shows "Zoo Ontology"

  Scenario: Set the ontology prefix from the overview
    Given the zoo ontology is open for editing
    When I set the ontology prefix to "zoo"
    Then the saved file declares the prefix "zoo"

  # Phase 6 — OWL properties

  Scenario: Add a domain class to a property
    Given the zoo ontology is open for editing
    When I add the domain class "Person" to the property "hasAge"
    Then the property "hasAge" has domain "Person"

  Scenario: Remove a domain class from a property
    Given the zoo ontology is open for editing
    When I remove the domain class "Animal" from the property "hasOwner"
    Then the property "hasOwner" does not have domain "Animal"

  Scenario: Add a range class to a property
    Given the zoo ontology is open for editing
    When I add the range class "Person" to the property "hasAge"
    Then the property "hasAge" has range "Person"

  Scenario: Delete a property and strip its values
    Given the zoo ontology is open for editing
    When I delete the property "hasOwner" choosing "strip"
    Then the property "hasOwner" no longer exists

  # Phase 12 — add a class property, add a new individual value

  Scenario: Define a new relationship property on a class
    Given the zoo ontology is open for editing
    When I add an object property "caresFor" on the class "Animal"
    Then the property "caresFor" exists
    And the property "caresFor" has domain "Animal"

  Scenario: Add a new object-property value to an individual
    Given the zoo ontology is open for editing
    When I add the value "Alice" for property "hasOwner" on the individual "Felix"
    Then the individual "Felix" has the value "Alice" for property "hasOwner"

  # Phase 14 — ontology base-URI / domain rename (cascades across entities)

  Scenario: Change the ontology base URI
    Given the zoo ontology is open for editing
    When I change the ontology base URI to "https://example.org/garden/"
    Then a class exists at "https://example.org/garden/Animal"
    And no class exists at "https://example.org/zoo/Animal"

  Scenario: Change the ontology domain
    Given the zoo ontology is open for editing
    When I change the ontology domain to "garden.example.org"
    Then a class exists at "https://garden.example.org/zoo/Animal"

  # Phase 7 — individual values
  # (schema:image add + markdown note were removed from the detail view)

  Scenario: Remove an object-property value from an individual
    Given the zoo ontology is open for editing
    When I remove the value "Alice" of property "hasOwner" from the individual "Rex"
    Then the individual "Rex" no longer has the value "Alice" for property "hasOwner"

  # Phase 8 — class ↔ individual punning

  Scenario: Convert an individual into a class
    Given the zoo ontology is open for editing
    When I convert the individual "Alice" to a class choosing "go"
    Then the class "Alice" exists
    And the individual "Alice" no longer exists

  Scenario: Convert a class into an individual deleting its instances
    Given the zoo ontology is open for editing
    When I convert the class "Eagle" to an individual choosing "delete"
    Then the individual "Eagle" exists
    And the class "Eagle" no longer exists

  # Phase 9 — create entities from a section header's right-click context menu

  Scenario: Create a top-level OWL class from the Ontology header
    Given the zoo ontology is open for editing
    When I create the OWL class "Reptile" from the tree
    Then the class "Reptile" exists

  Scenario: Create a SKOS concept scheme from the Taxonomy header
    Given the zoo ontology is open for editing
    When I create the scheme "Habitats" titled "Habitats" from the tree
    Then the scheme "Habitats" exists

  # Phase 10 — editing existing individual values

  Scenario: Change an object-property value on an individual
    Given the zoo ontology is open for editing
    When I change the value of property "hasOwner" on "Rex" from "Alice" to "Felix"
    Then the individual "Rex" has the value "Felix" for property "hasOwner"
    And the individual "Rex" no longer has the value "Alice" for property "hasOwner"

  # Phase 4 — SKOS concepts

  Scenario: Set a concept prefLabel
    Given a SKOS taxonomy is open for editing
    When I set the prefLabel of the concept "Top" to "Apex"
    Then the concept "Top" has prefLabel "Apex"

  Scenario: Set a concept definition
    Given a SKOS taxonomy is open for editing
    When I set the definition of the concept "Top" to "The root concept."
    Then the concept "Top" has definition "The root concept."

  Scenario: Add a definition to a concept
    Given a SKOS taxonomy is open for editing
    When I add a definition "A peer concept." to the concept "Sibling"
    Then the concept "Sibling" has definition "A peer concept."

  Scenario: Add a narrower concept
    Given a SKOS taxonomy is open for editing
    When I add a narrower concept "Leaf" under the concept "Top"
    Then the concept "Leaf" exists

  Scenario: Relate two concepts
    Given a SKOS taxonomy is open for editing
    When I relate the concept "Top" to the concept "Sibling"
    Then the concept "Top" is related to "Sibling"

  Scenario: Delete a concept
    Given a SKOS taxonomy is open for editing
    When I delete the concept "Child" choosing "keep"
    Then the concept "Child" no longer exists

  # Phase 5 — SKOS concept schemes

  Scenario: Set the scheme title
    Given a SKOS taxonomy is open for editing
    When I set the title of the scheme to "Catalogue"
    Then the scheme has title "Catalogue"

  Scenario: Add a top concept to the scheme
    Given a SKOS taxonomy is open for editing
    When I add a top concept "Brand" to the scheme
    Then the concept "Brand" exists

  # Phase 15 — generic ontology annotation overview (New-TUI only)

  Scenario: Ontology overview shows every annotation as a row
    Given an annotated ontology is open for editing
    When I open the ontology overview
    Then the overview shows an annotation row for "dcterms:creator"
    And the overview shows an annotation row for "dcterms:license"

  Scenario: Edit an existing annotation value
    Given an annotated ontology is open for editing
    When I edit the annotation "dcterms:creator" to "Bob"
    Then the ontology annotation "dcterms:creator" has value "Bob"

  Scenario: Remove one value of a multi-valued annotation
    Given an annotated ontology is open for editing
    When I remove the annotation "dcterms:creator" with value "Alice"
    Then the ontology annotation "dcterms:creator" no longer has value "Alice"
    And the ontology annotation "dcterms:creator" still has value "Charlie"

  Scenario: Add a new annotation via the catalog picker
    Given an annotated ontology is open for editing
    When I add the annotation "dcterms:publisher" with value "ACME"
    Then the ontology annotation "dcterms:publisher" has value "ACME"

  Scenario: Overview does not list OWL classes or properties
    Given an annotated ontology is open for editing
    When I open the ontology overview
    Then no class rows appear in the overview
    And no property rows appear in the overview

  # Phase 16 — create properties from their section-header context menus (New-TUI)

  Scenario: Add a datatype property from its header context menu
    Given the zoo ontology is open for editing
    When I add a "DatatypeProperty" named "age" from its properties header context menu
    Then the property "age" is a "DatatypeProperty"

  Scenario: Add an annotation property from its header context menu
    Given the zoo ontology is open for editing
    When I add an "AnnotationProperty" named "editorialNote" from its properties header context menu
    Then the property "editorialNote" is a "AnnotationProperty"

  # Phase 17 — responsive edits (targeted rebuild + busy indicator)

  Scenario: An edit keeps the tree consistent with the taxonomy
    Given the zoo ontology is open for editing
    When I add a subclass "Reptile" under the class "Animal"
    Then the class "Reptile" exists
    And the tree still matches the taxonomy

  Scenario: A property edit keeps the tree consistent
    Given the zoo ontology is open for editing
    When I add a "DatatypeProperty" named "weight" from its properties header context menu
    Then the property "weight" is a "DatatypeProperty"
    And the tree still matches the taxonomy
