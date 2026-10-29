"""Fixtures for tests using actual Home Assistant test helpers."""

import pytest


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    """Permit the test Home Assistant instance to load this integration."""
    yield
