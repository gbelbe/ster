Feature: URI quality checks detect local-filesystem and non-HTTP entity URIs

  Scenario: file:// class URI is reported as an error
    Given an OWL graph with a class whose URI starts with "file://"
    When I run the URI quality checks
    Then a URI001 error is reported for that entity

  Scenario: file:// property URI is reported as an error
    Given an OWL graph with a property whose URI starts with "file://"
    When I run the URI quality checks
    Then a URI001 error is reported for that entity

  Scenario: file:// individual URI is reported as an error
    Given an OWL graph with an individual whose URI starts with "file://"
    When I run the URI quality checks
    Then a URI001 error is reported for that entity

  Scenario: https:// class URI raises no violation
    Given an OWL graph with a class whose URI starts with "https://"
    When I run the URI quality checks
    Then no URI001 or URI002 violation is reported

  Scenario: non-HTTP scheme URI raises a warning
    Given an OWL graph with a class whose URI starts with "urn:"
    When I run the URI quality checks
    Then a URI002 warning is reported for that entity

  Scenario: built-in OWL and RDFS URIs are never flagged
    Given an OWL graph that only declares built-in OWL class relationships
    When I run the URI quality checks
    Then no URI001 or URI002 violation is reported

  Scenario: multiple file:// entities are all reported
    Given an OWL graph with 3 classes whose URIs start with "file://"
    When I run the URI quality checks
    Then 3 URI001 errors are reported

  Scenario: clean graph with only https:// URIs has no violations
    Given an OWL graph with 2 classes whose URIs start with "https://"
    When I run the URI quality checks
    Then no URI001 or URI002 violation is reported
