from __future__ import annotations

import pytest

from pal.agent import fetch as agent_fetch
from pal.agent.fetch import extract_article
from pal.agent.llm import LLMUnavailableError


def test_extract_article_calls_complete_with_url_context(mocker):
    spy = mocker.patch("pal.agent.fetch.complete", return_value="  extracted text  ")
    assert extract_article("https://example.com/a") == "extracted text"
    messages, kwargs = spy.call_args[0][0], spy.call_args[1]
    assert "https://example.com/a" in messages[-1]["content"]
    assert kwargs["tools"] == [{"url_context": {}}]


def test_extract_article_non_str_result_is_empty(mocker):
    mocker.patch("pal.agent.fetch.complete", return_value=None)
    assert extract_article("https://example.com/a") == ""


def test_extract_article_propagates_llm_unavailable(mocker):
    mocker.patch("pal.agent.fetch.complete", side_effect=LLMUnavailableError("nope"))
    with pytest.raises(LLMUnavailableError):
        extract_article("https://example.com/a")


def test_url_extract_prompt_is_single_user_message():
    msgs = agent_fetch.build_url_extract_prompt("https://example.com/a")
    assert len(msgs) == 1
    assert msgs[0]["role"] == "user"
    assert "https://example.com/a" in msgs[0]["content"]
