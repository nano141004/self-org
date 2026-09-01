from __future__ import annotations

import json

from pal.agent.prompts import IngestDecision, build_classification_prompt

SCHEMA_MD = (
    "# Schema\n\nEvery markdown file carries YAML frontmatter with `id`, "
    "`type`, `title`, `created`, `classified_into`, `sources`, and `tags`."
)
INDEX_MD = (
    "- `01HZAAA` `marketing/cold-email` Cold email subject lines "
    "→ raw/2026/04/26/01HZAAA--cold-email.md\n"
    "- `01HZBBB` `finance/budgeting` Envelope budgeting "
    "→ raw/2026/05/02/01HZBBB--envelope-budgeting.md"
)
RAW_TEXT = (
    "today I learned cold email subject lines under 5 words beat 30% open rates"
)


def test_system_prompt_embeds_schema_and_index():
    messages = build_classification_prompt(RAW_TEXT, SCHEMA_MD, INDEX_MD)
    system = messages[0]["content"]
    assert SCHEMA_MD in system
    assert INDEX_MD in system


def test_user_message_is_raw_text():
    messages = build_classification_prompt(RAW_TEXT, SCHEMA_MD, INDEX_MD)
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == RAW_TEXT


def test_ingest_decision_accepts_all_null_fields_and_round_trips():
    decision = IngestDecision.model_validate_json(
        json.dumps(
            {
                "class_path": None,
                "slug": None,
                "title": None,
                "body": None,
                "rationale": None,
            }
        )
    )
    assert decision.class_path is None
    assert decision.slug is None
    assert decision.title is None
    assert decision.body is None
    assert decision.rationale is None

    sample = json.dumps(
        {
            "class_path": "marketing/cold-email",
            "slug": "cold-email-subject-lines",
            "title": "Cold email subject lines under 5 words",
            "body": "Under 5 words beat 30% open rates.",
            "rationale": "Marketing topic",
        }
    )
    first = IngestDecision.model_validate_json(sample)
    second = IngestDecision.model_validate_json(first.model_dump_json())
    assert first == second
    assert first.class_path == "marketing/cold-email"
    assert first.slug == "cold-email-subject-lines"
    assert first.title == "Cold email subject lines under 5 words"
    assert first.body == "Under 5 words beat 30% open rates."
    assert first.rationale == "Marketing topic"


def _fake_index(n: int) -> str:
    return "\n".join(
        f"- `01HZ{str(i).zfill(20)}` `marketing/cold-email` "
        f"Cold email subject line {i} → raw/2026/09/01/"
        f"01HZ{str(i).zfill(20)}--cold-email-{i}.md"
        for i in range(n)
    )


def test_prompt_under_32k_with_1000_line_index():
    prompt = build_classification_prompt(RAW_TEXT, SCHEMA_MD, _fake_index(1000))
    assert len(json.dumps(prompt)) <= 32_000