Feature: Selecting text anywhere in the TUI copies it
  As someone reading an ontology in ster
  I want text I select with the mouse to be copied straight away
  So that copying never needs a second step, and I can see it happened where I was looking

  Background:
    Given the ontology browser is open on the source pane

  Scenario: Selecting text copies it and says so next to the selection
    When I drag the mouse across some Turtle
    Then the selected text is on the clipboard
    And "Copied to clipboard" appears where I released the mouse

  Scenario: It works inside a dialog too
    Given a dialog showing some text is open
    When I drag the mouse across the dialog's text
    Then the selected text is on the clipboard
    And "Copied to clipboard" appears where I released the mouse

  Scenario: Escape clears the selection and the message
    When I drag the mouse across some Turtle
    And I press escape
    Then nothing is selected
    And the message is gone

  Scenario: Clicking elsewhere clears the selection and the message
    When I drag the mouse across some Turtle
    And I click somewhere else
    Then nothing is selected
    And the message is gone
