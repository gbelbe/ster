Feature: Server starts on the configured address and port
  As a ster user
  I want the server to actually bind to the address and port I configured
  So that my browser extension and other tools can connect without manual changes

  Scenario: _start_api_server passes the configured port to uvicorn
    Given server config is set to URL "http://127.0.0.1" and port 9111
    When _start_api_server is invoked
    Then uvicorn.Config was called with port 9111

  Scenario: _start_api_server passes the configured host to uvicorn
    Given server config is set to URL "http://127.0.0.1" and port 9222
    When _start_api_server is invoked
    Then uvicorn.Config was called with host "127.0.0.1"

  Scenario: serve() uses the configured port from load_server_config
    Given server config is set to URL "http://127.0.0.1" and port 9333
    When serve() is called without explicit host or port
    Then uvicorn.run was called with port 9333

  Scenario: serve() uses the configured host from load_server_config
    Given server config is set to URL "http://127.0.0.1" and port 9333
    When serve() is called without explicit host or port
    Then uvicorn.run was called with host "127.0.0.1"

  Scenario: serve() respects an explicit port override
    Given server config is set to URL "http://127.0.0.1" and port 9333
    When serve() is called with explicit port 9444
    Then uvicorn.run was called with port 9444

  Scenario: A real server responds on the configured port
    Given server config is set to URL "http://127.0.0.1" and port 19766
    When the server is started via _start_api_server
    Then GET /api/graph on port 19766 returns HTTP 200
