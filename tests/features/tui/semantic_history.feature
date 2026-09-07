Feature: Read an ontology's history from the home menu

  The home menu opens the history of the selected file: the commits that touched
  it, newest first, with release tags beside the ones they mark. Selecting one
  shows what it did to the vocabulary. The raw git hunk is underneath, put away
  until asked for, because the text is the escape hatch rather than the first
  thing to read.

  Diffing a revision is expensive, so the list costs nothing to open: a commit is
  diffed when it is selected, and only once.

  Scenario: The home menu offers the history
    When the home action menu is built
    Then it offers a semantic history row
    And that row carries its own sentinel

  Scenario: A file outside a git repository has no history
    Given an ontology file that is not in a git repository
    When the history is opened
    Then no history is returned

  Scenario: The commits that touched the file are listed newest first
    Given a repository whose ontology changed in two commits
    When the history is opened
    Then the newest commit is listed first

  Scenario: A release tag is shown beside the commit it marks
    Given a repository whose ontology changed in two commits
    And the first commit is tagged "v0.1"
    When the history screen is opened
    Then the tag "v0.1" is shown beside that commit

  Scenario: Selecting a commit shows what it did to the vocabulary
    Given a repository whose ontology changed in two commits
    When the history screen is opened
    Then the newest commit's changes are shown

  Scenario: Opening the screen diffs only the commit it shows
    Given a repository whose ontology changed in two commits
    When the history screen is opened
    Then exactly one commit has been diffed

  Scenario: The raw diff is put away until asked for
    Given a repository whose ontology changed in two commits
    When the history screen is opened
    Then no raw diff is shown
    But pressing "r" shows the raw diff
