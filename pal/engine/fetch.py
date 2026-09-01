"""Fetch and extract readable article content (Phase 2b).

Engine-owned network I/O: httpx download + trafilatura extraction, with a
single LLM URL-context fallback pass for thin extractions. Any failure
raises FetchError — the caller files a minimal note; the URL is never lost.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import trafilatura

from pal.agent.fetch import extract_article
from pal.engine.errors import PalError

MAX_BODY_CHARS = 50_000
THIN_TEXT_CHARS = 200
LLM_EXTRACT_MIN_CHARS = 100
FETCH_TIMEOUT_S = 15.0
MAX_DOWNLOAD_BYTES = 2_000_000

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


class FetchError(PalError):
    """Fetching or extracting a URL failed; the URL stays the recoverable artifact."""


@dataclass(frozen=True)
class FetchedPage:
    url: str
    text: str
    via: str  # "trafilatura" | "llm"


def _client() -> httpx.Client:
    return httpx.Client(
        follow_redirects=True,
        timeout=FETCH_TIMEOUT_S,
        headers={"User-Agent": _USER_AGENT},
    )


def _download(url: str) -> str:
    with _client() as client:
        try:
            with client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    raise FetchError(f"{url}: HTTP {resp.status_code}")
                ctype = resp.headers.get("content-type", "")
                if "text/html" not in ctype:
                    raise FetchError(f"{url}: unsupported content-type {ctype!r}")
                chunks: list[str] = []
                total = 0
                for chunk in resp.iter_text():
                    chunks.append(chunk)
                    total += len(chunk)
                    if total >= MAX_DOWNLOAD_BYTES:
                        break
                return "".join(chunks)
        except FetchError:
            raise
        except Exception as exc:
            raise FetchError(f"{url}: download failed ({exc})") from exc


def _extract(html: str) -> str:
    try:
        text = trafilatura.extract(
            html,
            output_format="markdown",
            include_comments=False,
            include_tables=True,
        )
    except Exception:
        return ""
    return (text or "").strip()


def fetch_article(url: str) -> FetchedPage:
    """Fetch `url` and return readable content; LLM fallback for thin text."""
    html = _download(url)
    text = _extract(html)
    if len(text) >= THIN_TEXT_CHARS:
        return FetchedPage(url=url, text=text[:MAX_BODY_CHARS], via="trafilatura")
    try:
        text = extract_article(url).strip()
    except Exception as exc:
        raise FetchError(f"{url}: extraction failed ({exc})") from exc
    if len(text) >= LLM_EXTRACT_MIN_CHARS:
        return FetchedPage(url=url, text=text[:MAX_BODY_CHARS], via="llm")
    raise FetchError(f"{url}: no usable content extracted")
