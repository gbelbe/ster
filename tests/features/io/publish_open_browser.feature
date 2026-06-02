Feature: A dev publish opens its pages on the running web server

  Publishing to the dev channel writes a Turtle file and a pyLODE HTML page under
  ontology/dev/. The graph server exposes that tree at /ontology, so the freshly
  published pages can be opened directly in the browser as served URLs (the TTL
  first, then the HTML). When no server is available the same files are opened via
  file:// instead. A stable publish opens nothing.

  Scenario: Served URLs point at the dev pages under /ontology
    Given a dev publish wrote a Turtle file and an HTML page
    When I build the served URLs against the running server
    Then the URLs include the TTL and the HTML under /ontology/dev/
    And the TTL URL comes before the HTML URL

  Scenario: The graph server serves the published dev tree
    Given a dev publish wrote a Turtle file and an HTML page
    When I create the server with the publish directory mounted
    Then GET /ontology/dev/index.html returns the HTML page
    And GET the dev Turtle path returns the Turtle file

  Scenario: Opening falls back to file URLs when no server is available
    Given a dev publish wrote a Turtle file and an HTML page
    When I open the dev artifacts with no server available
    Then the opened URLs are file URLs for the TTL and the HTML
