Feature: Offer RDF files from subfolders, and remember the answers
  As someone whose project keeps vocabularies in folders of their own
  I want ster to offer the RDF files one level down, and remember what I chose
  So that I pick my files once, not every time I start ster

  Background:
    Given a project folder with "gear.ttl" at the top and "vocab/labels.ttl" one level down

  Scenario: Files one level down are offered after the user agrees
    When ster starts and I agree to include subfolders
    Then ster offers "gear.ttl" and "vocab/labels.ttl"

  Scenario: Declining keeps today's behaviour
    When ster starts and I decline to include subfolders
    Then ster offers only "gear.ttl"

  Scenario: Deeper, hidden and generated folders are never offered
    Given the folder also holds "vocab/old/draft.ttl", ".git/x.ttl" and "node_modules/gear.ttl"
    When ster starts and I agree to include subfolders
    Then ster offers "gear.ttl" and "vocab/labels.ttl"

  Scenario: The subfolder answer is remembered
    When ster starts and I agree to include subfolders
    And ster starts again
    Then I am not asked about subfolders the second time

  Scenario: The context chosen last time starts ticked
    Given I chose "vocab/labels.ttl" as context for "gear.ttl" last time
    When I open "gear.ttl" again
    Then "vocab/labels.ttl" starts ticked in the context checklist

  Scenario: A remembered context file that was deleted is dropped
    Given I chose "vocab/labels.ttl" as context for "gear.ttl" last time
    And "vocab/labels.ttl" has since been deleted
    And "places.ttl" is also in the folder
    When I open "gear.ttl" again
    Then nothing starts ticked in the context checklist
