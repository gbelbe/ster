"""Shared fixtures for BDD step definitions."""

from __future__ import annotations

import pytest


@pytest.fixture
def ask_fn():
    """Default ask_fn — always confirms. Overridden per-scenario by Given steps."""
    return lambda _: True
