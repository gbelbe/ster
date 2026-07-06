Feature: Search and add annotation properties from a curated library
  Authors add descriptive metadata predicates by searching a curated library of
  well-known annotation properties (by intent — "image", "homepage", "video", …),
  instead of hunting down URIs. Change-tracking provenance is not offered here.

  Scenario Outline: Find an annotation property by intent
    When I search the annotation library for "<intent>"
    Then "<label>" is among the results

    Examples:
      | intent   | label          |
      | image    | schema:image   |
      | video    | schema:video   |
      | webpage  | foaf:homepage  |
      | source   | dcterms:source |

  Scenario: Change-tracking provenance is excluded, descriptive source is kept
    Given the annotation library
    Then it does not offer "http://purl.org/dc/terms/created"
    And it offers "http://purl.org/dc/terms/source"

  Scenario: Adding a library property puts it in the ontology-metadata catalog
    Given the config modal is open on the Annotation properties tab
    When I pick "https://schema.org/image" from the library
    Then "https://schema.org/image" is in the ontology-metadata catalog
