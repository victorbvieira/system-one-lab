"""Shared fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture
def anyio_backend() -> str:
    """Pydantic Evals runs on anyio; the tests only ever need asyncio."""
    return "asyncio"
