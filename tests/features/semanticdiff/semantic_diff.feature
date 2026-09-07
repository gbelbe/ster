Feature: Read a git history of an ontology as semantic change, not as text

  A git diff on a .ttl file reports characters. An ontology author needs to know
  which classes, properties and concepts moved. semanticdiff walks the history of
  one tracked RDF file and reports each commit as a set of change operations over
  the vocabulary, so the raw text only has to be opened when the summary is not
  enough.

  # ── Layer 1: what changed between two versions of a graph ────────────────────

  Scenario: A class added between two versions is reported as an addition
    Given a base graph with class "ex:Product"
    And a later graph with classes "ex:Product" and "ex:Vehicle"
    When the two graphs are compared
    Then the changes include an added class "ex:Vehicle"
    And no class is reported as removed

  Scenario: A class removed between two versions is reported as a removal
    Given a base graph with classes "ex:Product" and "ex:LegacyStore"
    And a later graph with class "ex:Product"
    When the two graphs are compared
    Then the changes include a removed class "ex:LegacyStore"

  Scenario: A class that gains a subclass is reported as modified, not re-added
    Given a base graph with class "ex:Product"
    And a later graph where "ex:Vehicle" is a subclass of "ex:Product"
    When the two graphs are compared
    Then the changes include an added class "ex:Vehicle"
    And the changes include a modified class "ex:Product"
    And "ex:Product" is not reported as added

  Scenario: A class that gains a property through its domain is reported as modified
    Given a base graph with class "ex:Product"
    And a later graph where "ex:colour" is a property with domain "ex:Product"
    When the two graphs are compared
    Then the changes include a modified class "ex:Product"
    And the detail for "ex:Product" mentions "+1 property"

  Scenario: A label change is reported as a modification of that entity
    Given a base graph with class "ex:Product" labelled "Product"
    And a later graph with class "ex:Product" labelled "Article"
    When the two graphs are compared
    Then the changes include a modified class "ex:Product"

  Scenario: A property whose domain changes is reported as modified
    Given a base graph with property "ex:operatedBy" with domain "ex:Place"
    And a later graph with property "ex:operatedBy" with domain "ex:Site"
    When the two graphs are compared
    Then the changes include a modified property "ex:operatedBy"
    And the detail for "ex:operatedBy" mentions "domain ex:Place → ex:Site"

  Scenario: A SKOS concept added is reported as an added concept
    Given a base graph with concept "ex:Tools"
    And a later graph with concepts "ex:Tools" and "ex:Hammers"
    When the two graphs are compared
    Then the changes include an added concept "ex:Hammers"

  Scenario: An entity marked deprecated is reported as a deprecation
    Given a base graph with class "ex:LegacyStore"
    And a later graph where "ex:LegacyStore" is marked deprecated
    When the two graphs are compared
    Then the changes include a deprecated class "ex:LegacyStore"

  Scenario: A change inside a restriction is reported against the class that owns it
    Given a base graph where "ex:Car" restricts "ex:wheels" to 4
    And a later graph where "ex:Car" restricts "ex:wheels" to 3
    When the two graphs are compared
    Then the changes include a modified class "ex:Car"
    And no blank node is named in the changes

  # ── Layer 1: rename detection ────────────────────────────────────────────────

  Scenario: An entity given a new URI under the same label is reported as renamed
    Given a base graph with class "ex:Shop" labelled "Store"
    And a later graph with class "ex:Store" labelled "Store"
    When the two graphs are compared
    Then the changes include a rename from "ex:Shop" to "ex:Store"
    And "ex:Store" is not reported as added
    And "ex:Shop" is not reported as removed

  Scenario: A deletion and an unrelated addition are not mistaken for a rename
    Given a base graph with class "ex:Shop" labelled "Store"
    And a later graph with class "ex:Van" labelled "Van"
    When the two graphs are compared
    Then no rename is reported
    And the changes include a removed class "ex:Shop"
    And the changes include an added class "ex:Van"

  Scenario: Two entities sharing one label are not paired as a rename
    Given a base graph with classes "ex:ShopA" and "ex:ShopB" both labelled "Store"
    And a later graph with class "ex:Store" labelled "Store"
    When the two graphs are compared
    Then no rename is reported

  # ── Layer 1: what must NOT be reported ───────────────────────────────────────

  Scenario: Re-serialising a graph without editing it reports no change
    Given a base graph with class "ex:Product" labelled "Product"
    And a later graph that is the same graph serialised with reordered triples
    When the two graphs are compared
    Then no changes are reported

  Scenario: A graph whose blank nodes are relabelled reports no change
    Given a base graph with a restriction expressed through a blank node
    And a later graph that is the same graph with different blank node ids
    When the two graphs are compared
    Then no changes are reported

  # ── Layer 0: walking the git history ─────────────────────────────────────────

  Scenario: The history between two tags lists every commit that touched the ontology
    Given a repository whose ontology file was edited in three commits between "v0.1" and "v0.2"
    When the history is read between "v0.1" and "v0.2"
    Then three commits are reported
    And each reported commit carries its author, date and subject

  Scenario: A commit that does not touch the ontology file is left out
    Given a repository with one commit editing the ontology and one editing the README
    When the whole history is read
    Then one commit is reported

  Scenario: The commit that first introduces the ontology reports every entity as added
    Given a repository whose first commit adds an ontology with two classes
    When the whole history is read
    Then both classes are reported as added

  Scenario: An unknown revision is reported as an error, not an empty history
    Given a repository with one commit
    When the history is read for a revision that does not exist
    Then an error naming the unknown revision is raised

  Scenario: A revision where the ontology does not parse is reported without stopping the walk
    Given a repository whose middle commit leaves the ontology file unparseable
    When the whole history is read
    Then that commit is reported as unreadable
    And the surrounding commits are still reported

  # ── Layer 0: the summary ─────────────────────────────────────────────────────

  Scenario: The summary counts additions, modifications and removals across the range
    Given a history adding two classes, modifying one and removing one
    When the summary is rendered
    Then the summary states two additions, one modification and one removal

  # ── Layer 1: the per-commit view ─────────────────────────────────────────────

  Scenario: The per-commit view names the entities that changed in that commit
    Given a history whose commit adds class "ex:Vehicle"
    When the per-commit view is rendered
    Then the output names "ex:Vehicle" as added under that commit

  Scenario: The per-commit view prefers the entity label over its URI when one exists
    Given a history whose commit adds class "ex:Vehicle" labelled "Vehicle"
    When the per-commit view is rendered
    Then the output shows the label "Vehicle"

  Scenario: Non-RDF files in a commit are counted but not analysed
    Given a repository whose commit edits the ontology and two unrelated files
    When the per-commit view is rendered
    Then the output notes two non-RDF files changed

  # ── Layer 1: individuals are counted, not listed ────────────────────────────

  Scenario: A commit that adds a thousand individuals reports a count, not a thousand lines
    Given a history whose commit adds 200 individuals of class "City"
    When the per-commit view is rendered
    Then the output counts 200 individuals
    And the output does not name them one by one

  Scenario: Individuals are counted against the class they instantiate
    Given a history whose commit adds 200 individuals of class "City"
    When the per-commit view is rendered
    Then the count names the class "City"

  Scenario: A handful of individuals are still listed by name
    Given a history whose commit adds 3 individuals of class "City"
    When the per-commit view is rendered
    Then the output names them one by one

  Scenario: A commit that only reformats the file says so in as many words
    Given a repository whose commit only reformats the ontology
    When the per-commit view is rendered
    Then the output says the change was pure formatting

  # ── Layer 2: one entity's story ──────────────────────────────────────────────

  Scenario: Asking about one entity shows only that entity's history
    Given a history in which "ex:Product" changed twice and "ex:Van" changed once
    When the history of "ex:Product" is rendered
    Then only the two commits touching "ex:Product" are shown

  # ── Layer 3: the raw text, only on request ───────────────────────────────────

  Scenario: The raw text of a change is hidden by default
    Given a history whose commit adds class "ex:Vehicle"
    When the per-commit view is rendered without the text option
    Then no raw diff hunk appears in the output

  Scenario: The raw text of a change is shown when explicitly asked for
    Given a history whose commit adds class "ex:Vehicle"
    When the per-commit view is rendered with the text option
    Then the raw diff hunk appears in the output
