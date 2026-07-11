"""Tests for the Playwright-based web browser context."""

import pytest

from gitd.services import web_context


@pytest.fixture
def browser_session():
    """Create a fresh browser session for each test."""
    session = web_context.create_session(viewport={"width": 1280, "height": 720})
    yield session
    web_context.close_session(session.sid)


class TestWebContext:
    def test_create_session(self, browser_session):
        assert browser_session.sid

    def test_navigate(self, browser_session):
        result = web_context.navigate(browser_session.sid, "https://example.com")
        assert result["ok"]
        assert "example.com" in result["url"]

    def test_get_url_and_title(self, browser_session):
        web_context.navigate(browser_session.sid, "https://example.com")
        url = web_context.get_url(browser_session.sid)
        assert "example.com" in url
        title = web_context.get_title(browser_session.sid)
        assert isinstance(title, str)

    def test_screenshot(self, browser_session):
        result = web_context.screenshot(browser_session.sid)
        assert result["image"]
        assert result["width"] > 0
        assert result["height"] > 0

    def test_get_interactive_elements(self, browser_session):
        elements = web_context.get_interactive_elements(browser_session.sid)
        assert isinstance(elements, list)

    def test_get_screen_tree(self, browser_session):
        tree = web_context.get_screen_tree(browser_session.sid)
        assert isinstance(tree, str)
        assert "example" in tree.lower() or tree == "(empty page)"

    def test_set_viewport(self, browser_session):
        result = web_context.set_viewport(browser_session.sid, 390, 844)
        assert result["ok"]
        assert result["viewport"]["width"] == 390
        assert result["viewport"]["height"] == 844

    def test_tap_and_type(self, browser_session):
        web_context.navigate(browser_session.sid, "data:text/html,<input id='q'/>")
        web_context.tap(browser_session.sid, 10, 10)
        web_context.type_text(browser_session.sid, "hello")
        value = web_context.evaluate(browser_session.sid, "() => document.getElementById('q').value")
        assert value == "hello"

    def test_press_key(self, browser_session):
        web_context.press_key(browser_session.sid, "Tab")

    def test_list_sessions(self, browser_session):
        sessions = web_context.list_sessions()
        assert any(s["sid"] == browser_session.sid for s in sessions)

    def test_close_session(self):
        session = web_context.create_session()
        sid = session.sid
        assert web_context.close_session(sid)
        assert not web_context.close_session(sid)
