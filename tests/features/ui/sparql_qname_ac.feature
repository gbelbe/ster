Feature: SPARQL QName autocomplete

  The SPARQL editor provides an instant, scrollable, context-aware QName
  completion popup.  When the user types a known prefix followed by ":" the
  popup fires immediately from a pre-built index.  If the surrounding syntax
  expects a class (after "a", "rdf:type", "rdfs:subClassOf", etc.) the list
  is narrowed to OWL classes only.  All lists are in alphabetical order and
  are scrollable.

  Background:
    Given a taxonomy with two classes "Digital" and "Analog" and one individual "Device"

  Scenario: Typing a known prefix colon opens the popup immediately
    When the QName trigger fires for prefix "kai"
    Then the popup lists all local names for "kai" in alphabetical order
    And the popup includes both "Digital" and "Analog" and "Device"

  Scenario: Context "a kai:" shows only classes
    Given the cursor is after "a " in the query
    When the QName trigger fires for prefix "kai"
    Then the popup lists only class local names
    And "Digital" and "Analog" appear in the list
    And "Device" does not appear in the list

  Scenario: Context "rdfs:subClassOf kai:" shows only classes
    Given the cursor is after "rdfs:subClassOf " in the query
    When the QName trigger fires for prefix "kai"
    Then the popup lists only class local names

  Scenario: Generic context shows classes and individuals
    Given the cursor is in a generic position
    When the QName trigger fires for prefix "kai"
    Then the popup includes both "Digital" and "Device"

  Scenario: Popup items are in alphabetical order
    When the QName trigger fires for prefix "kai"
    Then the popup items are sorted alphabetically

  Scenario: Scroll keeps the selected item visible
    Given the popup has more items than fit in the visible window of 5 rows
    When the user moves the cursor down past the visible window
    Then qn_scroll advances so the selected item remains visible

  Scenario: Typing after the colon narrows the list
    When the QName trigger fires for prefix "kai" and the user types "Di"
    Then only "Digital" appears in the popup
    And "Analog" does not appear in the popup

  Scenario: URI index rebuilds when the file changes on disk
    Given the URI index has been built for a set of paths
    When the file modification time changes
    Then calling build_uri_index_cached returns a fresh index
