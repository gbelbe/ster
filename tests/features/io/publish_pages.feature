Feature: The publish screen lists the published pages as openable URLs

  The Version & Publish LD screen lists every page that exists under the publish
  directory — the auto-refreshed Dev pages, the Latest stable pages, and each
  versioned release — newest version first, each shown as a full URL the user can
  open in the browser. Groups that have nothing published yet are omitted.

  Scenario: Dev, Latest and versioned pages are all listed
    Given a publish directory with dev, latest and version "1.0.0" pages
    When I discover the published pages
    Then the groups listed are "Dev, Latest, v1.0.0"

  Scenario: Newer versions are listed before older ones
    Given a publish directory with versions "1.0.0" and "1.2.0" and "1.1.0"
    When I discover the published pages
    Then the version groups in order are "v1.2.0, v1.1.0, v1.0.0"

  Scenario: Each page is shown as a full server URL
    Given a publish directory with dev, latest and version "1.0.0" pages
    When I build the publish menu against server "http://127.0.0.1:8765"
    Then the first row publishes a new stable version
    And every page row label contains "http://127.0.0.1:8765/ontology/"

  Scenario: Groups with nothing published are omitted
    Given a publish directory with only latest pages
    When I discover the published pages
    Then the groups listed are "Latest"
