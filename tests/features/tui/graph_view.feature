Feature: Open the graph view from the tree with the "g" shortcut
  As a curator browsing the ontology tree I can press "g" to open (or update) the
  VOWL graph. It centres on the entity I have selected — an OWL class or
  individual — and falls back to the whole-ontology graph when the selection has
  nothing to focus on (the overview, a property or a concept).

  Scenario: Focus the graph on the selected class
    Given the zoo ontology is open in the browser
    When I select the class "Dog" in the tree and press "g"
    Then the graph opens focused on "Dog"

  Scenario: Focus the graph on the selected individual
    Given the zoo ontology is open in the browser
    When I select the individual "Rex" in the tree and press "g"
    Then the graph opens focused on "Rex"

  Scenario: Fall back to the global graph when nothing focusable is selected
    Given the zoo ontology is open in the browser
    When I show the ontology overview and press "g"
    Then the whole-ontology graph opens

  Scenario: Open the graph from the detail panel's highlighted action row
    Given the zoo ontology is open in the browser
    When I open the class "Dog" and activate its "Open Graph View" row
    Then the graph opens focused on "Dog"
