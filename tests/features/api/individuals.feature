Feature: Individual creation and query API
  As a developer building a Chrome extension
  I want to create and retrieve individuals over HTTP
  So that I can curate content and attach it to the ontology

  Background:
    Given the API server is running with the Animal/Dog/Tool ontology

  Scenario: Create individual with class URI and label returns 201
    When I POST /api/individuals with class "Dog" and label "Fido"
    Then the response status is 201
    And the response contains a "uri" field
    And the response "uri" ends with "Fido"

  Scenario: URI is derived from local_name hint
    When I POST /api/individuals with class "Dog", label "Rex", and local_name "RexTheDog"
    Then the response status is 201
    And the response "uri" ends with "RexTheDog"

  Scenario: URI collision appends numeric suffix
    Given individual "Buddy" of class "Dog" already exists
    When I POST /api/individuals with class "Dog" and local_name "Buddy"
    Then the response status is 201
    And the response "uri" ends with "Buddy_1"

  Scenario: Missing class_uri field returns 422
    When I POST /api/individuals without class_uri
    Then the response status is 422

  Scenario: Unknown class_uri returns 422
    When I POST /api/individuals with class_uri "https://example.org/onto#Ghost"
    Then the response status is 422

  Scenario: Create individual with object property assertion
    Given individual "Hammer1" of class "Tool" already exists
    When I POST /api/individuals with class "Dog", label "Rex", and property "uses" pointing to "Hammer1"
    Then the response status is 201
    And the individual "Rex" has property "uses" pointing to "Hammer1"

  Scenario: GET /api/individuals returns all individuals
    Given individual "Buddy" of class "Dog" already exists
    When I GET /api/individuals
    Then the response status is 200
    And the response list contains "Buddy"

  Scenario: GET /api/individuals filtered by type returns matching individuals only
    Given individual "Buddy" of class "Dog" already exists
    And individual "Hammer1" of class "Tool" already exists
    When I GET /api/individuals with type "Dog"
    Then the response status is 200
    And the response list contains "Buddy"
    And the response list does not contain "Hammer1"

  Scenario: Missing auth returns 401
    When I POST /api/individuals without Authorization header
    Then the response status is 401

  Scenario: Creating an individual invokes the save callback
    Given a tracked save function
    When I POST /api/individuals with class "Dog" and label "Fido"
    Then the save function was called once
