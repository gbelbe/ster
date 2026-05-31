Feature: ns1:note annotation property on OWL entities

  Scenario: New RDFClass has empty note
    Given a fresh RDFClass
    Then the note field is empty

  Scenario: New OWLIndividual has empty note
    Given a fresh OWLIndividual
    Then the note field is empty

  Scenario: New OWLProperty has empty note
    Given a fresh OWLProperty
    Then the note field is empty

  Scenario: Note round-trips through the store for a class
    Given a taxonomy with a class that has a note "Hello **world**"
    When the taxonomy is saved and reloaded
    Then the class note value is "Hello **world**"

  Scenario: Multiline note round-trips unchanged
    Given a taxonomy with a class that has a multiline note
    When the taxonomy is saved and reloaded
    Then all note lines are preserved

  Scenario: Empty note produces no RDF triple
    Given a taxonomy with a class that has an empty note
    When the taxonomy is serialised to a graph
    Then there is no ns1:note triple for that class

  Scenario: Note field appears in class detail view
    Given a taxonomy with a class that has a note "# Title"
    When I build the class detail fields
    Then a note_line field is present

  Scenario: Note field appears in individual detail view
    Given a taxonomy with an individual that has a note "# Title"
    When I build the individual detail fields
    Then a note_line field is present

  Scenario: Note field appears in object property detail view
    Given a taxonomy with a property that has a note "# Title"
    When I build the property detail fields
    Then a note_line field is present
