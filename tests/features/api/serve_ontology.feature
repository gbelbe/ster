Feature: Vocabulary serving endpoints
  As a linked-data publisher
  I want ster's API server to serve my ontology over HTTP
  So that browsers get documentation and RDF clients get machine-readable Turtle

  Scenario: Turtle is served when the client requests text/turtle
    Given a running ster API with a minimal taxonomy
    When the client requests "/onto" with Accept "text/turtle"
    Then the response status is 200
    And the Content-Type is "text/turtle"
    And the body contains "@prefix"

  Scenario: Turtle is the default when no Accept header is sent
    Given a running ster API with a minimal taxonomy
    When the client requests "/onto" with no Accept header
    Then the response status is 200
    And the Content-Type is "text/turtle"

  Scenario: 503 when browser requests HTML but no file is configured
    Given a running ster API with a minimal taxonomy and no file path
    When the client requests "/onto" with Accept "text/html"
    Then the response status is 503

  Scenario: VoWL visualization is served at /viz
    Given a running ster API with a VOWL renderer configured
    When the client requests "/viz"
    Then the response status is 200
    And the Content-Type starts with "text/html"

  Scenario: _derive_slug turns a file stem into a URL-safe slug
    Given the file path "/data/My Ontology v2.ttl"
    When I derive the slug
    Then the slug is "my-ontology-v2"

  Scenario: _derive_slug returns "onto" when file path is None
    Given no file path
    When I derive the slug
    Then the slug is "onto"
