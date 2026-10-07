Feature: Claiming the live-server port before opening a view
  Opening the graph, map or timeline needs ster's live server. Another process
  may already hold its port; ster resolves that without ever closing someone's
  open editor.

  Scenario: The port is free
    Given nothing holds the server port
    When a view is opened for "tax.ttl"
    Then the view opens on a fresh server

  Scenario: A server already shows this file
    Given a ster server of the same build is serving "tax.ttl"
    When a view is opened for "tax.ttl"
    Then that server is reused and nothing is closed

  Scenario: A server shows a different file
    Given a ster server is serving "other.ttl"
    When a view is opened for "tax.ttl" and the replacement is confirmed
    Then the old server is closed and a fresh one starts

  Scenario: Another interactive session holds the port
    Given another ster session is open on the server port
    When a view is opened for "tax.ttl"
    Then the user is told to close that session first
    And nothing is closed

  Scenario: Something that is not ster holds the port
    Given an unrelated process holds the server port
    When a view is opened for "tax.ttl"
    Then the user is told what holds the port
    And nothing is closed
