from __future__ import annotations

import subprocess
import sys

ENGINE_MODULES = [
    "pal.engine",
    "pal.engine.errors",
    "pal.engine.ingest",
    "pal.engine.query",
    "pal.engine.lint",
    "pal.config",
    "pal.storage.ids",
    "pal.storage.paths",
    "pal.storage.schema",
    "pal.storage.files",
    "pal.storage.git",
]

GUARD = """
import importlib, sys
for name in {modules!r}:
    importlib.import_module(name)
leaked = sorted(m for m in sys.modules if m.startswith(("pal.mcp", "pal.cli")))
if leaked:
    print("engine imported interface modules:", leaked)
    sys.exit(1)
"""


def test_engine_never_imports_mcp_or_cli():
    result = subprocess.run(
        [sys.executable, "-c", GUARD.format(modules=ENGINE_MODULES)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr