"""Shared fixtures for Whole Foods MCP integration tests.

These tests hit live Amazon — a valid session in .browser_state/state.json is required.
Run `login` + `save_session` via the MCP server before running tests.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import server


def pytest_collection_modifyitems(items):
    """Skip all tests if no valid Amazon session exists."""
    if not server.STORAGE_FILE.exists():
        skip = pytest.mark.skip(
            reason="No Amazon session found. Run `login` + `save_session` first."
        )
        for item in items:
            item.add_marker(skip)


@pytest.fixture(scope="session", autouse=True)
async def init_browser():
    """Initialize the browser once for the entire test session."""
    await server._ensure_context(headless=True)
    yield
    if server._browser:
        await server._browser.close()
    if server._playwright:
        await server._playwright.stop()


@pytest.fixture
async def clean_cart():
    """Clear the cart before and after a test that modifies it."""
    await server.clear_cart()
    yield
    await server.clear_cart()
