from __future__ import annotations

import subprocess
import sys

ENGINE_MODULES = [
    "pal.engine",
    "pal.engine.errors",
    "pal.engine.ingest",
    "pal.engine.query",
    "pal.engine.lint",
    "pal.engine.reading_list",
    "pal.config",
    "pal.storage.ids",
    "pal.storage.paths",
    "pal.storage.schema",
    "pal.storage.files",
    "pal.storage.git",
]

AGENT_MODULES = [
    "pal.agent",
    "pal.agent.llm",
    "pal.agent.prompts",
]

GUARD = """
import importlib, sys
for name in {modules!r}:
    importlib.import_module(name)
leaked = sorted(m for m in sys.modules if m.startswith({forbidden!r}))
if leaked:
    print("leaked interface modules:", leaked)
    sys.exit(1)
"""


def _assert_no_leak(modules: list[str], forbidden: tuple[str, ...]) -> None:
    result = subprocess.run(
        [sys.executable, "-c", GUARD.format(modules=modules, forbidden=forbidden)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_engine_never_imports_mcp_or_cli():
    _assert_no_leak(ENGINE_MODULES, ("pal.mcp", "pal.cli"))


def test_agent_never_imports_engine_or_interfaces():
    _assert_no_leak(AGENT_MODULES, ("pal.engine", "pal.mcp", "pal.cli"))