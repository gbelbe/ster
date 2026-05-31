Feature: OWL class deletion with subclass and individual handling

  Scenario: Building global overview fields does not require fastapi to be installed
    Given a taxonomy with OWL class "Leaf" only
    When I build the global overview fields without fastapi available
    Then no ModuleNotFoundError is raised

  Scenario: Deleting a leaf class with no subclasses and no individuals removes it immediately
    Given a taxonomy with OWL class "Leaf" only
    When I delete class "Leaf" with mode "keep_all"
    Then class "Leaf" does not exist in the taxonomy

  Scenario: Option keep_all re-parents direct subclasses to the deleted class's parent
    Given a taxonomy with OWL classes "GrandParent", "Parent", and "Child"
    And "Parent" is a subclass of "GrandParent"
    And "Child" is a subclass of "Parent"
    When I delete class "Parent" with mode "keep_all"
    Then class "Parent" does not exist in the taxonomy
    And class "Child" exists in the taxonomy
    And "Child" is a subclass of "GrandParent"

  Scenario: Option keep_all preserves individuals and re-types them to the deleted class's parent
    Given a taxonomy with OWL classes "Animal" and "Dog"
    And "Dog" is a subclass of "Animal"
    And an individual "Rex" typed as "Dog"
    When I delete class "Dog" with mode "keep_all"
    Then class "Dog" does not exist in the taxonomy
    And individual "Rex" exists in the taxonomy
    And individual "Rex" is typed as "Animal"

  Scenario: Option keep_all orphans individuals when the deleted class has no parent
    Given a taxonomy with OWL class "Dog" only
    And an individual "Rex" typed as "Dog"
    When I delete class "Dog" with mode "keep_all"
    Then class "Dog" does not exist in the taxonomy
    And individual "Rex" exists in the taxonomy
    And individual "Rex" has no types

  Scenario: Option cascade_subclasses deletes the entire subclass tree
    Given a taxonomy with OWL classes "GrandParent", "Parent", and "Child"
    And "Parent" is a subclass of "GrandParent"
    And "Child" is a subclass of "Parent"
    When I delete class "Parent" with mode "cascade_subclasses"
    Then class "Parent" does not exist in the taxonomy
    And class "Child" does not exist in the taxonomy
    And class "GrandParent" exists in the taxonomy

  Scenario: Option cascade_subclasses keeps individuals and re-types them to grandparent
    Given a taxonomy with OWL classes "Animal", "Dog", and "Poodle"
    And "Dog" is a subclass of "Animal"
    And "Poodle" is a subclass of "Dog"
    And an individual "Rex" typed as "Dog"
    And an individual "Tiny" typed as "Poodle"
    When I delete class "Dog" with mode "cascade_subclasses"
    Then class "Dog" does not exist in the taxonomy
    And class "Poodle" does not exist in the taxonomy
    And individual "Rex" exists in the taxonomy
    And individual "Rex" is typed as "Animal"
    And individual "Tiny" exists in the taxonomy
    And individual "Tiny" is typed as "Animal"

  Scenario: Option delete_all removes the class, all its descendants, and their individuals
    Given a taxonomy with OWL classes "Animal", "Dog", and "Poodle"
    And "Dog" is a subclass of "Animal"
    And "Poodle" is a subclass of "Dog"
    And an individual "Rex" typed as "Dog"
    And an individual "Tiny" typed as "Poodle"
    When I delete class "Dog" with mode "delete_all"
    Then class "Dog" does not exist in the taxonomy
    And class "Poodle" does not exist in the taxonomy
    And individual "Rex" does not exist in the taxonomy
    And individual "Tiny" does not exist in the taxonomy
    And class "Animal" exists in the taxonomy

  Scenario: Deletion removes the class from property domain and range references
    Given a taxonomy with OWL class "Dog" only
    And a property "hasMaster" with domain "Dog"
    When I delete class "Dog" with mode "keep_all"
    Then class "Dog" does not exist in the taxonomy
    And property "hasMaster" has no domain entries
