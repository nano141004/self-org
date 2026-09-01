from __future__ import annotations

import httpx
import pytest

from pal.engine.errors import PalError
from pal.engine import fetch as fetch_mod
from pal.engine.fetch import FetchError, FetchedPage, fetch_article


def _transport(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def test_fetch_article_success_trafilatura(monkeypatch):
    html = "<html><body><article>" + "word " * 100 + "</article></body></html>"
    monkeypatch.setattr(fetch_mod, "_client", lambda: _transport(
        lambda req: httpx.Response(200, text=html, headers={"content-type": "text/html"})))
    monkeypatch.setattr(fetch_mod.trafilatura, "extract",
                        lambda *a, **k: "A substantial article body of text. " * 20)
    page = fetch_article("https://example.com/post")
    assert page.via == "trafilatura"
    assert page.url == "https://example.com/post"
    assert len(page.text) >= 200


def test_fetch_article_thin_text_falls_back_to_llm(monkeypatch):
    html = "<html><body>hi</body></html>"
    monkeypatch.setattr(fetch_mod, "_client", lambda: _transport(
        lambda req: httpx.Response(200, text=html, headers={"content-type": "text/html"})))
    monkeypatch.setattr(fetch_mod.trafilatura, "extract", lambda *a, **k: "short")
    monkeypatch.setattr(fetch_mod, "extract_article", lambda url: "LLM extracted content. " * 30)
    page = fetch_article("https://example.com/js-heavy")
    assert page.via == "llm"


def test_fetch_article_both_fail_raises(monkeypatch):
    html = "<html><body>hi</body></html>"
    monkeypatch.setattr(fetch_mod, "_client", lambda: _transport(
        lambda req: httpx.Response(200, text=html, headers={"content-type": "text/html"})))
    monkeypatch.setattr(fetch_mod.trafilatura, "extract", lambda *a, **k: None)
    monkeypatch.setattr(fetch_mod, "extract_article", lambda url: "")
    with pytest.raises(FetchError):
        fetch_article("https://example.com/empty")


def test_fetch_article_non_html_rejected(monkeypatch):
    monkeypatch.setattr(fetch_mod, "_client", lambda: _transport(
        lambda req: httpx.Response(200, text="%PDF-1.4", headers={"content-type": "application/pdf"})))
    with pytest.raises(FetchError):
        fetch_article("https://example.com/doc.pdf")


def test_fetch_article_http_404(monkeypatch):
    monkeypatch.setattr(fetch_mod, "_client", lambda: _transport(
        lambda req: httpx.Response(404, text="nope", headers={"content-type": "text/html"})))
    with pytest.raises(FetchError):
        fetch_article("https://example.com/gone")


def test_fetch_article_network_error_wrapped(monkeypatch):
    def raise_timeout(req):
        raise httpx.ConnectTimeout("timed out")
    monkeypatch.setattr(fetch_mod, "_client", lambda: _transport(raise_timeout))
    with pytest.raises(FetchError):
        fetch_article("https://slow.example.com")


def test_fetch_article_body_capped(monkeypatch):
    html = "<html><body>x</body></html>"
    monkeypatch.setattr(fetch_mod, "_client", lambda: _transport(
        lambda req: httpx.Response(200, text=html, headers={"content-type": "text/html"})))
    monkeypatch.setattr(fetch_mod, "MAX_BODY_CHARS", 50)
    monkeypatch.setattr(fetch_mod.trafilatura, "extract", lambda *a, **k: "y" * 500)
    assert len(fetch_article("https://example.com/big").text) == 50


def test_fetch_error_is_pal_error():
    assert issubclass(FetchError, PalError)
