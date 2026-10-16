# Working on self-org / pal

## Direction

Build a personal second brain for mixed dumps: aha moments, ideas, intentions,
books, links, and selected material from past conversations.

- pal preserves captures, interprets useful items, and maintains connections,
  records, and navigation information.
- Organization should choose creation, enrichment, connection, or revision
  using incoming meaning and relevant existing context.
- External agents use the store guide, index, readable files, and their own
  search/read tools to investigate questions and synthesize answers.
- Do not make dedicated browse/find/open tools, internal answering, or a
  particular search/database technology prerequisites for the first iteration.
- A local agent needs filesystem access; an index alone does not give an
  MCP-only client access to the underlying files.
- Jev is a possible later decision component, not a selected dependency.

## Discussion, documentation, and implementation

- Lead realignment in chat, one topic or decision at a time. Explain the
  experience, actual code, gap, and next concrete change.
- Keep chat digestible. Do not make the owner read large documents to
  participate. Update related docs when requested; the owner explicitly
  requested alignment of the documentation and first implementation plan.
- Use README as the entry point, PRD for aligned product direction, DESIGN
  for implemented contracts/future boundaries, ITERATION-1 for the delivered iteration, and
  CODEBASE for actual behavior and validation evidence.
- Product direction and worked examples are aligned. The owner authorized
  Iteration 1 implementation after the documentation pass. Format-2 records,
  navigation, retry, and compatibility guards are implemented; keep docs
  consistent with actual behavior and remaining limits.
- Iteration 1 is plain text -> preserved original -> several linked items ->
  guide/index -> agent navigation, including incomplete states and retry.
- Context-aware updates across captures follow in Iteration 2. Dedicated chat
  import, article enrichment on the new format, page maintenance, and Jev are
  later scope.
- No automatic migration or real-brain access follows from a design example.
  The first iteration uses opt-in new stores and explicit legacy
  compatibility boundaries.

## Testing policy

- Do not run tests unless the owner explicitly asks. This includes full
  suites, individual tests, smoke/integration checks, and application-running
  verification scripts. Do not substitute a custom script for a test run.
- A request to implement, fix, or continue work is not a request to run tests.
  Iteration checkpoints and implementation uncertainty do not override this rule.
- When tests are explicitly requested, run only the smallest relevant subset
  for the changed behavior and directly affected files. Prefer specific test
  cases over entire modules. Do not run a full suite or broad regression batch
  without a separate explicit request.
- Do not add tests for instruction or documentation changes. Keep existing
  tests; this rule concerns execution, not removal of coverage.
- Inspect edits through static review, read-back, and diffs. Do not present
  those reviews as proof that runtime behavior passed tests.
- Do not run live provider calls or lengthy builds as routine verification.
- State when tests were not run and why: they were not explicitly requested.

## Working conventions

- Always prefix shell commands with `rtk`; use `rtk proxy` for raw commands.
- Preserve existing work and distinguish decisions, proposals, actual
  behavior, and evidence. Keep AGENTS.md eligible for version control.
- Preserve originals and attribution. Separate reading progress, processing
  state, uncertainty, and the origin of an interpretation.
- Matching excerpts and valid IDs establish traceability, not semantic truth.
- User data lives outside this repo. Use temporary stores for verification.
- Retain a reusable engine and shared model-call layer behind CLI/MCP.
- Stable IDs, local readable files, and Git are current foundations to assess.
  Atomic per-file writes and Git history do not create a multi-file transaction.
- Update docs when agreed implementation changes actual behavior. Keep
  historical test/probe dates explicit.
- Use conventional commits only when requested; omit attribution trailers.
