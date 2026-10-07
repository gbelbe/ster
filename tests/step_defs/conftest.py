"""Shared fixtures for BDD step definitions."""

from __future__ import annotations

import pytest


@pytest.fixture
def ask_fn():
    """Default ask_fn — always confirms. Overridden per-scenario by Given steps."""
    return lambda _: True


@pytest.fixture
def api_client():
    """A client on a running ster API over a one-class taxonomy (token "tok")."""
    from fastapi.testclient import TestClient

    from ster.api import SSEBroadcaster, create_app
    from ster.model import Label, LabelType, RDFClass, Taxonomy

    ns = "https://example.org/onto#"
    tax = Taxonomy()
    tax.namespace_bindings[""] = ns
    tax.owl_classes[ns + "Thing"] = RDFClass(
        uri=ns + "Thing", labels=[Label(lang="en", value="Thing", type=LabelType.PREF)]
    )
    return TestClient(create_app(tax, "tok", SSEBroadcaster(), save_fn=lambda _t: None))
