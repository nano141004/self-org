from __future__ import annotations

from pal.engine.triage import Route, route


def test_route_bare_url():
    result = route("https://example.com/some-article")
    assert result == Route(kind="link", url="https://example.com/some-article")


def test_route_first_line_url_with_short_rest():
    text = "https://example.com/article\nshort note about this link"
    result = route(text)
    assert result == Route(kind="link", url="https://example.com/article")


def test_route_multi_url_first_wins():
    result = route("https://first.example.com/a https://second.example.com/b")
    assert result == Route(kind="link", url="https://first.example.com/a")


def test_route_long_non_url_text_returns_none():
    text = " ".join(["just some ordinary prose"] * 40)
    assert len(text) > 200
    assert route(text) is None


def test_route_www_without_scheme_returns_none():
    assert route("www.example.com") is None