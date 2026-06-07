Feature: Ontology publication pipeline

  # ── Model + store ─────────────────────────────────────────────────────────

  Scenario: version_info round-trips through save and load
    Given a taxonomy with ontology URI "https://ex.org/onto" and version_info "1.1.0"
    When I save and reload the taxonomy
    Then taxonomy.version_info is "1.1.0"

  Scenario: version_iri round-trips through save and load
    Given a taxonomy with version_iri "https://ex.org/onto/1.1.0"
    When I save and reload the taxonomy
    Then taxonomy.version_iri is "https://ex.org/onto/1.1.0"

  Scenario: prior_version round-trips through save and load
    Given a taxonomy with prior_version "https://ex.org/onto/1.0.0"
    When I save and reload the taxonomy
    Then taxonomy.prior_version is "https://ex.org/onto/1.0.0"

  # ── Version string building ────────────────────────────────────────────────

  Scenario: build_version_string produces semver+date+sha
    Given base version "1.2.0", date "20260528", sha "abc1234"
    When I build the version string
    Then the result is "1.2.0+20260528.abc1234"

  Scenario: bump_version patch
    Given current version "1.1.0"
    When I bump with kind "patch"
    Then the bumped result is "1.1.1"

  Scenario: bump_version minor
    Given current version "1.1.0"
    When I bump with kind "minor"
    Then the bumped result is "1.2.0"

  Scenario: bump_version major
    Given current version "1.1.0"
    When I bump with kind "major"
    Then the bumped result is "2.0.0"

  # ── patch_version_triples ─────────────────────────────────────────────────

  Scenario: patch_version writes owl:versionInfo to file
    Given a taxonomy file with ontology URI "https://ex.org/onto"
    When I patch version "1.2.0+20260528.abc1234" with base "1.2.0"
    Then the file contains owl:versionInfo "1.2.0+20260528.abc1234"

  Scenario: patch_version writes owl:versionIRI
    Given a taxonomy file with ontology URI "https://ex.org/onto"
    When I patch version "1.2.0+20260528.abc1234" with base "1.2.0"
    Then the file contains owl:versionIRI "https://ex.org/onto/1.2.0"

  Scenario: patch_version writes owl:priorVersion when prior exists
    Given a taxonomy file with ontology URI "https://ex.org/onto" and prior_version "https://ex.org/onto/1.1.0"
    When I patch version "1.2.0+20260528.abc1234" with base "1.2.0"
    Then the file contains owl:priorVersion "https://ex.org/onto/1.1.0"

  Scenario: patch_version writes dcterms:modified with today's date
    Given a taxonomy file with ontology URI "https://ex.org/onto"
    When I patch version "1.2.0+20260528.abc1234" with base "1.2.0"
    Then the file contains a dcterms:modified date

  Scenario: dev patch_version does NOT modify source file
    Given a source taxonomy file at path "onto.ttl"
    When I run write_dev_artifacts
    Then the source file is unchanged

  # ── Artifact generation ───────────────────────────────────────────────────

  Scenario: stable publish writes versioned directory
    Given publish_dir and version "1.2.0"
    When I write stable artifacts for "1.2.0+20260528.abc1234"
    Then the versioned TTL exists under "v1.2.0"

  Scenario: stable publish overwrites latest/
    Given publish_dir with existing "latest/onto.ttl"
    When I write stable artifacts for "1.2.0+20260528.abc1234"
    Then "latest/onto.ttl" contains "1.2.0+20260528.abc1234"

  Scenario: dev publish overwrites dev/ unconditionally
    Given publish_dir with existing "dev/onto.ttl"
    When I run write_dev_artifacts
    Then "dev/onto.ttl" exists with updated content

  Scenario: dev publish creates dev/ if it does not exist
    Given publish_dir with no dev directory
    When I run write_dev_artifacts
    Then "dev/onto.ttl" exists

  # ── Gate: pre-flight ──────────────────────────────────────────────────────

  Scenario: publish blocked when ontology_uri is missing
    Given a taxonomy with no ontology URI set
    When I run pre_flight check
    Then pre_flight raises PublishError mentioning "ontology URI"

  # ── FastAPI serving ───────────────────────────────────────────────────────

  Scenario: FastAPI serves versioned TTL
    Given a running API with publish_dir containing "v1.2.0/onto.ttl"
    When I GET "/published/v1.2.0/onto.ttl"
    Then the response status is 200

  Scenario: FastAPI serves latest TTL
    Given a running API with publish_dir containing "latest/onto.ttl"
    When I GET "/published/latest/onto.ttl"
    Then the response status is 200

  Scenario: FastAPI serves dev channel TTL
    Given a running API with publish_dir containing "dev/onto.ttl"
    When I GET "/published/dev/onto.ttl"
    Then the response status is 200
