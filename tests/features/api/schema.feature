Feature: Schema introspection API
  As a developer building a Chrome extension
  I want to query the ontology schema over HTTP
  So that I can present classes and applicable properties to the user

  Background:
    Given the API server is running with the Animal/Dog/Tool ontology

  Scenario: List all classes returns 200 with class list
    When I GET /api/classes
    Then the response status is 200
    And the response contains classes "Animal", "Dog", "Cat", "Tool", "Hammer"

  Scenario: Response includes parent and child links
    When I GET /api/classes
    Then "Dog" has "Animal" in its sub_class_of list
    And "Animal" has "Dog" and "Cat" in its child_classes list

  Scenario: Class detail includes applicable object properties
    When I GET /api/classes with uri "Dog"
    Then the response status is 200
    And the class detail includes property "uses" with range "Hammer"

  Scenario: Unknown class URI returns 404
    When I GET /api/classes with uri "NonExistent"
    Then the response status is 404

  Scenario: Missing Authorization header returns 401
    When I GET /api/classes without Authorization header
    Then the response status is 401

  Scenario: Wrong token returns 401
    When I GET /api/classes with wrong token
    Then the response status is 401
