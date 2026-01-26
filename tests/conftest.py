"""Pytest configuration and shared fixtures."""

import pytest


@pytest.fixture(scope="module")
def anyio_backend():
    """Configure anyio to use asyncio backend."""
    return "asyncio"
