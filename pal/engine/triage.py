from __future__ import annotations

import re
from dataclasses import dataclass


URL_PATTERN = re.compile(r"https?://\S+")
MAX_REST = 200


@dataclass(frozen=True)
class Route:
    kind: str
    url: str


def route(content: str) -> Route | None:
    """Deterministic URL-only routing: link captures become reading-list items.

    Returns a link Route when the whole content is a single URL, or when the
    first line contains a URL and the text after that URL is at most 200 chars.
    Everything else (long prose, schemeless `www.` links) returns None and
    needs the LLM.
    """
    text = content.strip()
    if not text:
        return None

    if re.fullmatch(URL_PATTERN, text):
        return Route(kind="link", url=text)

    lines = text.splitlines()
    match = URL_PATTERN.search(lines[0])
    if match and len(text[match.end() :]) <= MAX_REST:
        return Route(kind="link", url=match.group(0))

    return None