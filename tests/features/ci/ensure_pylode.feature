Feature: Automatic pyLODE installation guard

  The "Generate Web-Documentation" menu calls _ensure_pylode before running
  the export.  It must prompt the user, install pyLODE if agreed, and
  invalidate Python's import cache so the newly installed package is usable
  in the same process.

  Scenario: pyLODE is already installed — guard returns ready without prompting
    Given pyLODE is importable
    When the pylode guard runs
    Then it returns True without showing any prompt

  Scenario: User declines installation — guard returns not-ready
    Given pyLODE is not installed
    When the user is asked to install and declines
    Then the guard returns False

  Scenario: User cancels with Ctrl+C — guard returns not-ready
    Given pyLODE is not installed
    When the user interrupts the install prompt with Ctrl+C
    Then the guard returns False

  Scenario: Installation succeeds — guard returns ready
    Given pyLODE is not installed
    And the user agrees to install
    When the installer runs and succeeds
    Then the guard returns True

  Scenario: Installation fails — guard returns not-ready
    Given pyLODE is not installed
    And the user agrees to install
    When the installer runs and fails
    Then the guard returns False

  Scenario: Import cache is invalidated after install attempt
    Given pyLODE is not installed
    And the user agrees to install
    When the installer runs
    Then the Python import cache is invalidated regardless of outcome

  Scenario: uv in PATH — installer uses uv pip install
    Given pyLODE is not installed
    And the user agrees to install
    And uv is available on PATH at "/usr/local/bin/uv"
    When the installer runs and succeeds
    Then the command uses uv with "--python" targeting the current interpreter

  Scenario: uv not in PATH — installer falls back to python -m pip
    Given pyLODE is not installed
    And the user agrees to install
    And uv is not available on PATH
    When the installer runs and succeeds
    Then the command uses the current interpreter with "-m" "pip"

  Scenario: Subprocess is run with captured output
    Given pyLODE is not installed
    And the user agrees to install
    When the installer runs and succeeds
    Then the subprocess is called with capture_output=True
