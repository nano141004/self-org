from __future__ import annotations

import logging
import re
from pathlib import Path

from pydantic import BaseModel, Field

from pal.agent.llm import LLMUnavailableError, complete
from pal.agent.prompts import (
    ContradictionResult,
    FoldingResult,
    TaxonomyResult,
    build_lint_contradiction_prompt,
    build_lint_folding_prompt,
    build_lint_taxonomy_prompt,
)
from pal.engine.errors import BrainNotInitializedError, NotImplementedPhaseError
from pal.storage import git, schema
from pal.storage.files import read_note
from pal.storage.paths import brain_dir, sanitize_slug

logger = logging.getLogger(__name__)

_SLUG_MAX = 60
_SLUG_RE = re.compile(r"^[a-z0-9-]+$")


def _sanitize_slug(slug: str) -> str:
    if _SLUG_RE.match(slug) and len(slug) <= _SLUG_MAX:
        return slug
    return sanitize_slug(slug)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class Candidate(BaseModel):
    id: str
    path: Path
    title: str
    created: str
    classified_into: str | None = None
    sources: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    snippet: str = ""  # body[:400]


class Move(BaseModel):
    id: str
    from_path: str
    to_class: str | None = None
    to_path: str
    reason: str = ""


class CreateConcept(BaseModel):
    topic: str
    slug: str
    title: str
    body: str
    sources: list[str] = Field(default_factory=list)  # len≥3


class FlagContradiction(BaseModel):
    note_id: str
    conflicts_with: list[str] = Field(default_factory=list)
    note: str = ""


class SchemaRec(BaseModel):
    suggestion: str
    rationale: str


class LintChangeset(BaseModel):
    moves: list[Move] = Field(default_factory=list)
    concepts: list[CreateConcept] = Field(default_factory=list)
    flags: list[FlagContradiction] = Field(default_factory=list)
    schema_recs: list[SchemaRec] = Field(default_factory=list)
    partial_failures: list[str] = Field(default_factory=list)


class LintResult(BaseModel):
    changeset: LintChangeset
    commit_hash: str | None = None
    applied: bool = False


# ---------------------------------------------------------------------------
# Candidate collection
# ---------------------------------------------------------------------------


def _resolve_brain_dir(explicit: Path | None) -> Path:
    if explicit is not None:
        return Path(explicit)
    return brain_dir()


def _ensure_initialized(resolved: Path, explicit: bool) -> None:
    if explicit:
        # Custom dir: check required files exist.
        if not (
            resolved.is_dir()
            and (resolved / "INDEX.md").is_file()
            and (resolved / "LOG.md").is_file()
            and (resolved / "SCHEMA.md").is_file()
        ):
            raise BrainNotInitializedError("brain not initialized — run 'pal init' first")
        # Also require .git for consistency with engine guard; if missing treat as not init.
        if not (resolved / ".git").is_dir():
            raise BrainNotInitializedError("brain not initialized — run 'pal init' first")
    else:
        if not (schema.is_initialized() and git.is_repo()):
            raise BrainNotInitializedError("brain not initialized — run 'pal init' first")


def collect_candidates(brain_dir: Path | None = None) -> list[Candidate]:
    """Collect inbox/*.md + raw/**/*.md candidates.

    - Respects BrainNotInitializedError.
    - Ignores wiki/, reading-list/, INDEX.md, LOG.md.
    - Skips files missing id (warn).
    - snippet = body.strip()[:400].replace("\\n"," ")
    - Sorted by created asc for stable diffs.
    """
    resolved = _resolve_brain_dir(brain_dir)
    _ensure_initialized(resolved, explicit=brain_dir is not None)

    candidates: list[Candidate] = []

    inbox_dir = resolved / "inbox"
    raw_dir = resolved / "raw"

    paths: list[Path] = []
    if inbox_dir.is_dir():
        # inbox/*.md only (non-recursive)
        paths.extend(inbox_dir.glob("*.md"))
    if raw_dir.is_dir():
        paths.extend(raw_dir.rglob("*.md"))

    for p in paths:
        # Defensive: ignore any path that somehow escaped to wiki/reading-list etc.
        # (glob above already limits roots, but rglob filter is explicit)
        try:
            # Ensure path is inside inbox or raw (extra guard for symlink oddities)
            rel = p.relative_to(resolved)
        except ValueError:
            continue
        parts = rel.parts
        if not parts:
            continue
        # Only allow inbox/* or raw/** ; already guaranteed, but double-check
        if parts[0] not in ("inbox", "raw"):
            continue
        # Ignore INDEX.md / LOG.md even if inside those roots (should not happen)
        if p.name in ("INDEX.md", "LOG.md", "SCHEMA.md"):
            continue

        try:
            fm, body = read_note(p)
        except Exception as exc:  # unreadable / parse error -> skip, warn
            logger.warning("lint: skip unreadable %s: %s", p, exc)
            continue

        note_id = fm.get("id")
        if not note_id:
            logger.warning("lint: skip %s missing id", p)
            continue

        title = str(fm.get("title") or "")
        created = str(fm.get("created") or "")
        classified_into = fm.get("classified_into")
        if classified_into is not None:
            classified_into = str(classified_into).strip() or None
        # Normalize sources/tags to list[str]
        sources_raw = fm.get("sources") or []
        tags_raw = fm.get("tags") or []
        if not isinstance(sources_raw, list):
            sources_raw = []
        if not isinstance(tags_raw, list):
            tags_raw = []
        sources = [str(s) for s in sources_raw if s is not None]
        tags = [str(t) for t in tags_raw if t is not None]

        snippet = body.strip()[:400].replace("\n", " ")

        candidates.append(
            Candidate(
                id=str(note_id),
                path=p,
                title=title,
                created=created,
                classified_into=classified_into,
                sources=sources,
                tags=tags,
                snippet=snippet,
            )
        )

    candidates.sort(key=lambda c: c.created)
    return candidates


# ---------------------------------------------------------------------------
# Heuristic grouping
# ---------------------------------------------------------------------------


def group_for_folding(candidates: list[Candidate]) -> dict[str, list[Candidate]]:
    """Group by classified_into or first tag or 'inbox'; only groups len≥3."""
    groups: dict[str, list[Candidate]] = {}
    for c in candidates:
        if c.classified_into:
            key = c.classified_into
        elif c.tags:
            key = c.tags[0]
        else:
            key = "inbox"
        groups.setdefault(key, []).append(c)
    # Only groups eligible for folding prompt (len≥3)
    return {k: v for k, v in groups.items() if len(v) >= 3}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _is_inside_brain(to_path: str, brain_root: Path) -> bool:
    """Return True iff to_path is a safe relative path inside brain_root."""
    if not to_path or not to_path.strip():
        return False
    p = Path(to_path)
    if p.is_absolute() or p.drive or p.root:
        return False
    if ".." in p.parts:
        return False
    try:
        (brain_root / p).relative_to(brain_root)
    except ValueError:
        return False
    return True


def validate_changeset(
    cs: LintChangeset, cands: list[Candidate], brain_dir: Path | None = None
) -> LintChangeset:
    """Validate and sanitize changeset.

    - Move.id must exist in candidates.
    - Move.to_path inside brain_dir, no traversal, slug sanitized, no overwrite.
    - CreateConcept topic/slug sanitized, body non-empty, sources len≥3 and all exist.
    - FlagContradiction.note_id must exist.
    - Returns sanitized copy; logs validation_dropped if any dropped.
    """
    brain_root = _resolve_brain_dir(brain_dir)
    candidate_ids = {c.id for c in cands}
    # Also build set of candidate paths for from_path validation? Not required.

    dropped = 0
    valid_moves: list[Move] = []
    for m in cs.moves:
        if m.id not in candidate_ids:
            dropped += 1
            logger.warning("lint validate: drop move bad id %s", m.id)
            continue
        if not _is_inside_brain(m.to_path, brain_root):
            dropped += 1
            logger.warning("lint validate: drop move bad to_path %s", m.to_path)
            continue

        # Sanitize to_path slug if filename contains "--"
        sanitized_to_path = m.to_path
        p = Path(sanitized_to_path)
        # If filename like id--slug.md, sanitize slug part
        if "--" in p.name:
            # stem without suffix
            stem = p.stem
            if "--" in stem:
                id_part, slug_part = stem.split("--", 1)
                # slug_part is the slug; validate
                if not _SLUG_RE.match(slug_part) or len(slug_part) > _SLUG_MAX:
                    new_slug = _sanitize_slug(slug_part)
                    new_name = f"{id_part}--{new_slug}.md"
                    sanitized_to_path = (p.parent / new_name).as_posix()
                    p = Path(sanitized_to_path)

        # Bonus: filename id-part must equal Move.id to prevent cross-id move
        stem_check = p.stem
        if "--" not in stem_check:
            dropped += 1
            logger.warning("lint validate: drop move bad filename %s", sanitized_to_path)
            continue
        id_part_check = stem_check.split("--", 1)[0]
        if id_part_check != m.id:
            dropped += 1
            logger.warning("lint validate: drop move cross-id %s != %s", id_part_check, m.id)
            continue

        # File not exists unless same id (overwrite only own concept upgrade)
        dest = brain_root / sanitized_to_path
        if dest.exists():
            try:
                fm, _ = read_note(dest)
                existing_id = str(fm.get("id") or "")
                if existing_id != m.id:
                    dropped += 1
                    logger.warning("lint validate: drop move overwrite %s", sanitized_to_path)
                    continue
            except Exception:
                # Unreadable dest -> treat as exists and drop to be safe
                dropped += 1
                logger.warning("lint validate: drop move unreadable dest %s", sanitized_to_path)
                continue

        # Sanitize to_class (strip slashes, keep or null)
        sanitized_to_class: str | None = m.to_class
        if sanitized_to_class is not None:
            sanitized_to_class = sanitized_to_class.strip().strip("/")
            if sanitized_to_class == "":
                sanitized_to_class = None
            # Optional: topic-like sanitize? Keep as-is but could sanitize segments
            # We keep original segments, but if to_class contains illegal chars we keep;
            # validation doesn't drop on to_class alone.

        valid_moves.append(
            Move(
                id=m.id,
                from_path=m.from_path,
                to_class=sanitized_to_class,
                to_path=sanitized_to_path,
                reason=m.reason,
            )
        )

    valid_concepts: list[CreateConcept] = []
    for cc in cs.concepts:
        # Topic sanitized (like paths.sanitize_slug)
        sanitized_topic = sanitize_slug(cc.topic) if cc.topic else "untitled"
        # Slug sanitized
        sanitized_slug = cc.slug or ""
        if not sanitized_slug:
            sanitized_slug = sanitize_slug(cc.title or "untitled")
        else:
            if not _SLUG_RE.match(sanitized_slug) or len(sanitized_slug) > _SLUG_MAX:
                sanitized_slug = _sanitize_slug(sanitized_slug)

        # Body non-empty
        if not cc.body or not cc.body.strip():
            dropped += 1
            logger.warning("lint validate: drop concept empty body %s", cc.title)
            continue

        # Sources len≥3 and all exist
        if len(cc.sources) < 3:
            dropped += 1
            logger.warning("lint validate: drop concept sources<3 %s", cc.title)
            continue
        if not all(s in candidate_ids for s in cc.sources):
            dropped += 1
            logger.warning("lint validate: drop concept bad sources %s", cc.sources)
            continue

        # File not exists check for wiki/<topic>/<slug>.md (any id with same slug)
        # Since concept id not yet known, check glob for existing slug collision.
        wiki_dir = brain_root / "wiki" / sanitized_topic
        if wiki_dir.is_dir():
            # Any file ending with --<slug>.md ?
            try:
                existing_matches = list(wiki_dir.glob(f"*--{sanitized_slug}.md"))
            except Exception:
                existing_matches = []
            if existing_matches:
                # If any match exists, drop to avoid overwrite (concepts don't have id to compare)
                dropped += 1
                logger.warning("lint validate: drop concept slug exists %s/%s", sanitized_topic, sanitized_slug)
                continue

        valid_concepts.append(
            CreateConcept(
                topic=sanitized_topic,
                slug=sanitized_slug,
                title=cc.title,
                body=cc.body,
                sources=list(cc.sources),
            )
        )

    valid_flags: list[FlagContradiction] = []
    for f in cs.flags:
        if f.note_id not in candidate_ids:
            dropped += 1
            logger.warning("lint validate: drop flag bad note_id %s", f.note_id)
            continue
        # conflicts_with may include wiki ids (outside candidates) — allowed, no check
        valid_flags.append(f)

    # SchemaRecs: keep all (no validation)
    valid_schema = list(cs.schema_recs)

    if dropped:
        logger.warning("validation_dropped: %d", dropped)

    return LintChangeset(
        moves=valid_moves,
        concepts=valid_concepts,
        flags=valid_flags,
        schema_recs=valid_schema,
        partial_failures=list(cs.partial_failures),
    )


# ---------------------------------------------------------------------------
# Helpers for plan_lint
# ---------------------------------------------------------------------------


def _read_file_safe(path: Path) -> str:
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8")
    except Exception as exc:  # pragma: no cover
        logger.warning("lint: cannot read %s: %s", path, exc)
    return ""


def _layout_stats(cands: list[Candidate]) -> dict[str, int]:
    stats: dict[str, int] = {}
    for c in cands:
        if c.classified_into:
            key = c.classified_into
        elif c.tags:
            key = c.tags[0]
        else:
            key = "inbox"
        stats[key] = stats.get(key, 0) + 1
    return stats


def _folding_preview(concepts: list[CreateConcept]) -> dict[str, int]:
    preview: dict[str, int] = {}
    for cc in concepts:
        topic = cc.topic or "untitled"
        preview[topic] = preview.get(topic, 0) + 1
    return preview


def _collect_wiki_snippets(
    brain_root: Path, limit: int = 5, snippet_len: int = 600
) -> list[dict]:
    """Collect up to `limit` wiki snippets sorted by path for stability."""
    wiki_root = brain_root / "wiki"
    if not wiki_root.is_dir():
        return []
    snippets: list[dict] = []
    try:
        paths = sorted(wiki_root.rglob("*.md"))
    except Exception:  # pragma: no cover
        paths = []
    for p in paths[:limit]:
        try:
            fm, body = read_note(p)
        except Exception as exc:
            logger.warning("lint: skip wiki unreadable %s: %s", p, exc)
            continue
        nid = str(fm.get("id") or "")
        title = str(fm.get("title") or "")
        # body truncated to snippet_len
        text = (body or "").strip()[:snippet_len].replace("\n", " ")
        snippets.append({"id": nid, "title": title, "body": text})
    return snippets


def _to_engine_concepts(raw: list) -> list[CreateConcept]:
    out: list[CreateConcept] = []
    for rc in raw or []:
        try:
            if isinstance(rc, dict):
                out.append(CreateConcept.model_validate(rc))
            elif isinstance(rc, CreateConcept):
                out.append(rc)
            elif hasattr(rc, "model_dump"):
                out.append(CreateConcept.model_validate(rc.model_dump()))
            else:
                out.append(
                    CreateConcept(
                        topic=str(getattr(rc, "topic", "")),
                        slug=str(getattr(rc, "slug", "")),
                        title=str(getattr(rc, "title", "")),
                        body=str(getattr(rc, "body", "")),
                        sources=list(getattr(rc, "sources", []) or []),
                    )
                )
        except Exception as exc:  # pragma: no cover
            logger.warning("lint folding: skip invalid concept %s: %s", rc, exc)
    return out


def _to_engine_moves(raw: list) -> list[Move]:
    out: list[Move] = []
    for rm in raw or []:
        try:
            if isinstance(rm, dict):
                out.append(Move.model_validate(rm))
            elif isinstance(rm, Move):
                out.append(rm)
            elif hasattr(rm, "model_dump"):
                out.append(Move.model_validate(rm.model_dump()))
            else:
                out.append(
                    Move(
                        id=str(getattr(rm, "id", "")),
                        from_path=str(getattr(rm, "from_path", "")),
                        to_class=getattr(rm, "to_class", None),
                        to_path=str(getattr(rm, "to_path", "")),
                        reason=str(getattr(rm, "reason", "")),
                    )
                )
        except Exception as exc:  # pragma: no cover
            logger.warning("lint taxonomy: skip invalid move %s: %s", rm, exc)
    return out


def _to_engine_flags(raw: list) -> list[FlagContradiction]:
    out: list[FlagContradiction] = []
    for rf in raw or []:
        try:
            if isinstance(rf, dict):
                out.append(FlagContradiction.model_validate(rf))
            elif isinstance(rf, FlagContradiction):
                out.append(rf)
            elif hasattr(rf, "model_dump"):
                out.append(FlagContradiction.model_validate(rf.model_dump()))
            else:
                out.append(
                    FlagContradiction(
                        note_id=str(getattr(rf, "note_id", "")),
                        conflicts_with=list(getattr(rf, "conflicts_with", []) or []),
                        note=str(getattr(rf, "note", "")),
                    )
                )
        except Exception as exc:  # pragma: no cover
            logger.warning("lint contradiction: skip invalid flag %s: %s", rf, exc)
    return out


def _to_engine_schema_recs(raw: list) -> list[SchemaRec]:
    out: list[SchemaRec] = []
    for rs in raw or []:
        try:
            if isinstance(rs, dict):
                out.append(SchemaRec.model_validate(rs))
            elif isinstance(rs, SchemaRec):
                out.append(rs)
            elif hasattr(rs, "model_dump"):
                out.append(SchemaRec.model_validate(rs.model_dump()))
            else:
                out.append(
                    SchemaRec(
                        suggestion=str(getattr(rs, "suggestion", "")),
                        rationale=str(getattr(rs, "rationale", "")),
                    )
                )
        except Exception as exc:  # pragma: no cover
            logger.warning("lint contradiction: skip invalid schema_rec %s: %s", rs, exc)
    return out


def plan_lint(brain_dir: Path | None = None) -> LintChangeset:
    """Plan a lint pass (no writes).

    1. collect_candidates + group_for_folding
    2. 3 sequential LLM calls (folding, taxonomy, contradiction+schema)
       each wrapped in ``try/except LLMUnavailableError`` — partial failures
       keep successful sub-results and log a warning.
    3. ``validate_changeset`` the aggregated result.
    """
    cands = collect_candidates(brain_dir)
    groups = group_for_folding(cands)

    resolved = _resolve_brain_dir(brain_dir)
    schema_md = _read_file_safe(resolved / "SCHEMA.md")
    index_md = _read_file_safe(resolved / "INDEX.md")

    layout_stats = _layout_stats(cands)
    wiki_snippets = _collect_wiki_snippets(resolved, limit=5)
    candidates_slice = cands[:10]

    cs = LintChangeset()
    partial_failures: list[str] = []
    folding_preview: dict[str, int] = {}

    # Call 1 — folding
    try:
        folding = complete(
            build_lint_folding_prompt(schema_md, index_md, groups),
            response_model=FoldingResult,
        )
        cs.concepts = _to_engine_concepts(getattr(folding, "concepts", []))
        folding_preview = _folding_preview(cs.concepts)
    except LLMUnavailableError as exc:
        logger.warning("lint plan: folding failed partial_failure=folding: %s", exc)
        partial_failures.append("folding")
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("lint plan: folding unexpected error partial_failure=folding: %s", exc)
        partial_failures.append("folding")

    # Call 2 — taxonomy
    try:
        taxonomy = complete(
            build_lint_taxonomy_prompt(
                schema_md, index_md, layout_stats, folding_preview
            ),
            response_model=TaxonomyResult,
        )
        cs.moves = _to_engine_moves(getattr(taxonomy, "moves", []))
    except LLMUnavailableError as exc:
        logger.warning("lint plan: taxonomy failed partial_failure=taxonomy: %s", exc)
        partial_failures.append("taxonomy")
    except Exception as exc:  # pragma: no cover
        logger.warning("lint plan: taxonomy unexpected error partial_failure=taxonomy: %s", exc)
        partial_failures.append("taxonomy")

    # Call 3 — contradiction + schema
    try:
        contra = complete(
            build_lint_contradiction_prompt(
                schema_md, wiki_snippets, candidates_slice
            ),
            response_model=ContradictionResult,
        )
        cs.flags = _to_engine_flags(getattr(contra, "flags", []))
        cs.schema_recs = _to_engine_schema_recs(
            getattr(contra, "schema_recs", [])
        )
    except LLMUnavailableError as exc:
        logger.warning(
            "lint plan: contradiction failed partial_failure=contradiction: %s", exc
        )
        partial_failures.append("contradictions")
    except Exception as exc:  # pragma: no cover
        logger.warning(
            "lint plan: contradiction unexpected error partial_failure=contradiction: %s",
            exc,
        )
        partial_failures.append("contradictions")

    cs.partial_failures = partial_failures
    return validate_changeset(cs, cands, brain_dir)


def run_lint(*args, **kwargs) -> None:  # type: ignore[no-untyped-def]
    """Weekly reorganization pass — full implementation ships in Phase 3.

    Phase A provides models + collect/group/validate only; LLM orchestration
    and apply are added in later phases. This placeholder preserves the
    Phase-2 stub contract for tests.
    """
    raise NotImplementedPhaseError("lint", "3")
