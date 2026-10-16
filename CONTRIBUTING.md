# Contributing

pal is an early-stage Python project. The current focus is reliable capture,
source-linked records, and navigation by external agents.

Start with [the README](README.md), then use [the design](docs/DESIGN.md) and
[codebase guide](docs/CODEBASE.md) to locate the relevant behavior.
[Milestone 1](docs/ITERATION-1.md) describes delivered scope and future work.

## Development setup

Requirements: Python 3.11+ and Git.

```sh
python -m venv .venv
```

Activate the environment using `source .venv/bin/activate` on macOS/Linux
or `.\.venv\Scripts\Activate.ps1` in PowerShell, then install:

```sh
python -m pip install -e ".[dev]"
```

Copy `.env.example` to `.env` when provider-backed work is needed.
Use a temporary `BRAIN_DIR` for experiments; application data belongs
outside the source tree.

## Working with the architecture

- Keep CLI and MCP as adapters over reusable engine behavior.
- Define shared record/proposal/result contracts in `pal/models.py`.
- Keep model utilities independent of engine and interface imports.
- Preserve exact capture payloads and distinguish interpretation from evidence.
- Keep stable IDs, source references, and recovery behavior intact.
- Maintain the format boundary; do not silently convert existing stores.
- Update public documentation when commands, record fields, or behavior change.

Cross-capture revision is planned work. Changes to that area should describe
identity matching, uncertain links, source history, and human-edit handling
before changing existing records automatically.

## Verification

Prefer the smallest checks that exercise the changed behavior. For example,
a capture-recovery change can start with the relevant case:

```sh
python -m pytest -q tests/test_capture.py -k model_failure
```

Non-live fixtures use temporary stores, isolate provider credentials, and
mock model/fetch calls. Live tests are marked `live` and excluded by default.
Provider-backed verification requires deliberate configuration.

Useful coverage checks behavior at the relevant boundary: preserved bytes,
source/relationship resolution, truthful failure states, repeat processing,
and compatibility. Schema validity alone does not assess interpretation quality.

Describe which checks ran and their limits in the change description. Keep
verification scoped to the change rather than treating every edit as a reason
to repeat an unrelated suite.

## Documentation

Write for someone encountering the project for the first time. Explain the
problem, behavior, examples, and current limits without relying on private
conversation history or local machine paths.

Keep implemented capabilities distinct from roadmap items. Source references
and historical verification results should retain their limitations.
