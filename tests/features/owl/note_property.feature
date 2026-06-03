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

  Scenario: A long note shows only its first line plus an open button
    Given a taxonomy with a class that has a multiline note
    When I build the class detail fields
    Then exactly one note_line field is shown
    And a more-lines hint is present
    And an open-note action is present

  Scenario: Pressing Esc in the note editor saves the note (auto-save)
    Given a saved taxonomy file with a class
    And the note editor is open with text "decision: use SKOS"
    When I press Esc in the note editor
    Then the saved file's class note is "decision: use SKOS"

  Scenario: Pressing Ctrl+S in the note editor saves the note
    Given a saved taxonomy file with a class
    And the note editor is open with text "saved via ctrl s"
    When I press Ctrl+S in the note editor
    Then the saved file's class note is "saved via ctrl s"
