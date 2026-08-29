from __future__ import annotations

import pytest

from pal.engine.errors import NotImplementedPhaseError
from pal.engine.lint import run_lint
from pal.engine.query import assemble_context, query


@pytest.mark.parametrize(
    ("fn", "args", "phase"),
    [
        (query, ("any question",), "4"),
        (assemble_context, (["topic"],), "4"),
        (run_lint, (), "3"),
    ],
)
def test_stubs_raise_typed_phase_error(fn, args, phase):
    with pytest.raises(NotImplementedPhaseError) as exc_info:
        fn(*args)
    assert exc_info.value.phase == phase
    assert f"not implemented until Phase {phase}" in str(exc_info.value)