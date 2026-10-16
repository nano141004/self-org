# Codebase: current implementation and review findings

Updated: 2026-10-16. Iteration 1 extends legacy baseline `469f37a` with
capture-first storage and agent navigation. The initial legacy audit/probes date
from 2026-10-09; their results are historical, not freshly rerun probes.
Read [PRD](PRD.md), [DESIGN](DESIGN.md), and [ITERATION-1](ITERATION-1.md)
for direction and the completed first-iteration sequence.

## 1. Current state

The shared Python engine supports two isolated store formats. CLI and MCP
dispatch according to the store guide's `store_format` marker; unversioned
stores remain legacy format 1. Format 2 requires explicit initialization in
a new empty directory. There is no migration or automatic guide replacement.

| Capability | Current behavior |
|---|---|
| Legacy text classification | One model-classified note; original-preservation limitations remain |
| Format-2 capture | Exact engine-received UTF-8 text plus separate metadata |
| Mixed input | Zero or more interpreted items, canonical engine IDs, source quotes, and within-capture links |
| Non-URL reading resource | Supported by format-2 reading items |
| Agent navigation | Format-2 guide, descriptive catalog, readable records, source/relationship IDs |
| Incomplete work/retry | Capture state and durable plan; retries reuse item IDs and logical log events |
| Reading-list projection | Both formats; new-format output includes IDs, paths, sources, contexts, progress, and processing state |
| Article fetch/summary | Legacy only; refused on format 2 |
| Lint | Legacy only; format-2 planning/application refused |
| Cross-capture enrichment/revision | Iteration 2; not implemented |
| Dedicated chat import / maintained format-2 wiki | Deferred |
| Internal query/context assembly | Stubs; not required for agent-led navigation |
| pal reindex | Placeholder; separate from internal catalog reconstruction |
| Jev | Deferred; no integration or dependency |

Reading progress is supplied by the interpreter when supported, otherwise
unknown. Proposed URLs must appear literally in the capture. These checks
do not establish that all extracted meanings are faithful.

## 2. Implemented flows

```text
Format 1 text -> URL router or classification -> one note -> index/log -> commit
Format 1 URL  -> dedup -> fetch -> summary -> reading note -> index/log -> commit
Format 1 lint -> raw/inbox -> model proposals -> validate -> preview/apply

Format 2 text -> exact original + metadata -> pending catalog/log -> capture commit
              -> interpret -> validate -> durable plan with allocated IDs
              -> items/links -> catalog/log/state -> organization commit

External agent -> guide -> search index/files -> read item -> follow source/links
```

Capture is synchronous; original acceptance precedes interpretation. Model
failures remain distinct from persistence failures. Capture results identify
the store, guide/index, original/capture paths, materialized items, processing
state, history state, and warnings.

The operation record persists intended file hashes before each managed write,
so retry can recognize writes on either side of a crash. Conflicting manual
changes are reported without overwrite. Missing/tampered originals are not
reported as currently preserved. A store-level OS advisory lock serializes
pal writers and releases on exit; external editors do not participate.

Git and catalog/log failures leave recoverable state. Final-history failure
can report complete organization with pending history; whole-operation
success requires both. A completed retry does not reinterpret or add commits.
Fresh identical submissions remain distinct occurrences.

This is resumable application, not multi-file rollback. Record paths are
brain-relative and checked for traversal/symlink escape before managed writes.
New saves reject staged changes; retry permits only its operation's staged
paths and checks canonical content against its recorded hashes.

## 3. Data stays outside the code repository

`BRAIN_DIR` configures the location; the default is `~/brain/`.
Verification uses temporary stores. Actual owner data was not accessed.

Legacy layout:

```text
raw/YYYY/MM/DD/  classified notes, not guaranteed exact originals
inbox/          unclassified legacy notes
reading-list/   fetched URL entries
wiki/<topic>/   new legacy concepts
INDEX.md        one-line catalog
LOG.md          operation log
SCHEMA.md       existing guide/rules
.index/         scaffold only
.git/           Git history
```

Format-2 layout, in a separately initialized directory:

```text
captures/YYYY/MM/DD/<id>.txt  exact engine-received original
captures/YYYY/MM/DD/<id>.md   origin, hash, processing state, item IDs
items/<id>--<slug>.md         interpreted item plus sources/relations
.operations/<id>.json        recovery record and intended file hashes
.operations/write.lock      ignored OS-held writer lock
SCHEMA.md                    concise guide with store_format: 2
INDEX.md                     rebuilt navigation catalog
LOG.md                       idempotent capture/organization events
.gitattributes               -text for original payloads, preserving Git bytes
.gitignore                   exclude the lock file
.git/                        capture and organization history
```

Canonical records remain readable independently of the catalog. The initial
catalog implementation scans the records when rebuilding; large-store
performance and index partitioning remain unmeasured.

An agent needs actual filesystem access. MCP save responses include location
information but do not themselves grant read access to an MCP-only client.

## 4. Legacy findings and remaining limits

These targeted findings describe the original prototype. The new capture
flow addresses preservation/recovery in format 2; it does not silently repair
old data or claim the legacy implementation has been rewritten.

| Historical finding | Legacy consequence / current boundary |
|---|---|
| Classification stores a model body | Original wording can disappear; format-2 payloads are separate |
| Fetch failure drops commentary | Reason for saving a link can disappear; new-format fetching is deferred |
| Summarized duplicate URL drops new commentary | Resource dedup can discard new personal context |
| Broad ingest catch includes persistence | Simulated commit failure created two notes and an LLM warning; new flow separates these boundaries |
| Move source is not bound to note identity | Legacy content, filename, and catalog can diverge |
| Lint applies sequential writes | Failure can leave partial files; no rollback transaction |
| MCP lint preview/apply replans independently | Applied changes can differ from the preview |
| Links excluded from lint candidates | Resources do not contribute to legacy synthesis |
| Concepts have no update operation | Same-slug concepts rejected; no maintained-page refresh |
| No contribution checkpoint | Original candidates remain eligible; generated slugs can multiply pages |
| Short/fixed synthesis context | 400-character snippets, first eight notes/group, 12 groups; contradiction sampling covers first ten candidates/five wiki paths |
| Source membership/count checks | Traceability does not prove faithful synthesis |
| Legacy reading status mutation | Engine-only; format-2 cross-capture progress updates are deferred |

Other retained limits:

- Legacy lint combines collection, models, validation, rendering, orchestration,
  and persistence. Prompt/engine changeset models are duplicated.
- `engine.lint.run_lint` is an obsolete placeholder; adapters call
  `plan_lint`/`apply_changeset`.
- The model budget is checked before attempts, with no enforced in-flight
  timeout. A historical mocked 0.01-second budget returned after about 0.05s.
- Structured-call fallback may issue two provider requests per outer attempt.
- Legacy Git commits the current index. Format 2 adds staged-path preflight
  around its operation; legacy semantics are unchanged.
- Guide templates now use correct pal commands and describe their format.
  Existing custom/legacy guides are deliberately not rewritten.
- `rich` remains a direct import without a direct dependency declaration.
- Provider/model availability was not checked live.
- Source validation checks exact quotes, not semantic entailment, correct
  attribution, or calibrated uncertainty. No real-model quality evaluation ran.
- Deletion, completed-item reinterpretation, cross-capture matching, human-edit
  reconciliation, and new-format page maintenance need later contracts.

## 5. Validation and limits

Current policy: run tests only on the owner's explicit request, limited to
changed behavior and directly affected files. Iteration checkpoints do not
authorize testing. The commands/results below are historical evidence, not
instructions to repeat these batches. See AGENTS.md.

Implementation checkpoint, 2026-10-16:

```powershell
rtk proxy .venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests/test_capture.py tests/test_capture_interfaces.py tests/test_files.py tests/test_paths.py tests/test_schema.py tests/test_git.py tests/test_cli_add.py tests/test_mcp.py tests/test_reading_list.py tests/test_add_link.py tests/test_engine_ingest.py tests/test_engine_imports.py tests/test_lint_cli.py tests/test_lint_mcp.py tests/test_lint_storage.py
```

**186 passed**, two Typer/Click deprecation warnings, **125.30 seconds**.
Coverage includes original bytes in working files and Git, pre-model
acceptance, multi-item/source/link navigation, no-item interpretation,
failure/retry of metadata/item/catalog/log/commit work, completed retry,
manual edits, staged-work protection, locks, CLI/MCP, format guards, and
affected legacy behavior.

Final review tightened unknown reading progress, literal URL support, and
tampered-original reporting. A subsequent targeted run passed **five checks**
in **19.18 seconds**, with the same two warnings: original/navigation flow,
unknown progress, invented URL rejection, changed-original handling, and MCP
save/read/retry. Two checks were reruns; this is not 191 unique tests.

All providers were mocked and stores were temporary. No live provider call,
package build, actual-brain access, or migration ran. The full repository
suite was not rerun after the focused checkpoint. Structural checks and
mocked fixtures do not prove real-model faithfulness, usefulness, provider
reliability, or large-store performance.

Historical baseline, 2026-10-09: **285 passed, five live tests deselected**,
two dependency warnings, 94.77 seconds. Eight separate exploratory probes
confirmed the legacy findings: lost original wording, lost fetch-failure
commentary, lost duplicate-URL commentary, mismatched move source, rejected
same-slug concept, excluded readings/reused candidates, duplicate notes after
commit failure, and a model call exceeding its configured budget.
Those probes were disposable scripts, not newly run checks.

## 6. Module map

Paths are relative to pal/.

| Area | Modules | Responsibility |
|---|---|---|
| Shared records | models.py | Capture/item/proposal/operation/result contracts |
| Settings/IDs | config.py, storage/ids.py | Data root, provider settings, canonical IDs |
| File/path helpers | storage/files.py, paths.py | Atomic bytes/Markdown, exact original reads, checked paths |
| Records/recovery | storage/records.py | Serialization, durable plans, hashes, lock |
| Navigation | storage/catalog.py | Derived descriptive catalog and pending/partial states |
| Setup/log/history | storage/schema.py, git.py | Format detection, guide/init, logical events, scoped history |
| New capture flow | engine/capture.py | Preserve, interpret, validate, plan, apply, report, retry |
| Dispatch/legacy capture | engine/ingest.py, triage.py | Format dispatch and retained legacy text/URL flow |
| Article enrichment | engine/fetch.py, agent/fetch.py | Legacy HTTP extraction and model fallback |
| Reading lists | engine/reading_list.py | Both-format projection; legacy status update |
| Legacy organization | engine/lint.py | Legacy-only proposals/application |
| Models/prompts | agent/llm.py, prompts.py | Shared calls and interpretation/legacy prompts |
| Internal query | engine/query.py | Legacy stubs |
| Interfaces | cli/main.py, mcp/server.py | CLI and MCP adapters |

MCP tools: add_to_brain, retry_capture, get_reading_list, run_lint.
Format-2 responses expose navigation/state/source details; legacy capture and
reading-list response shapes remain compatible.

## 7. Next work

Iteration 2 introduces context-aware maintenance of existing material. Start
with the four-capture Book X example: new reason, more specific application,
reading completion/takeaway, and changed project assessment.

Define matching, revision, uncertainty, source history, and human-edit handling
before enabling automatic cross-capture updates. Dedicated import, article
enrichment, maintained pages, MCP-only read transport, scale improvements,
and a possible Jev decision component remain later work.

## 8. Documentation and cleanup

Active map: README -> PRD -> DESIGN -> ITERATION-1; use CODEBASE for actual
behavior and evidence, AGENTS.md for contributor instructions/testing cadence.
All were aligned to the implementation. AGENTS.md is visible to Git, and
package metadata points to README.md.

Removed tracked phase plans remain in Git at 469f37a. Pre-cleanup docs/local
planning notes were backed up at:

`C:\Users\nano\AppData\Local\Temp\self-org-realignment-20261009T084903663555Z`

That is temporary local backup; Git is durable history for tracked docs.
The Iteration 1 commit includes the implementation, aligned documentation,
earlier planning cleanup, package readme metadata, and the owner's rule to
run tests only on explicit request.
