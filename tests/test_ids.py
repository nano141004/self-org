from __future__ import annotations

import re

from brain.storage.ids import new_id


ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


def test_new_id_format():
    assert ULID_RE.match(new_id())


def test_new_id_unique_at_scale():
    ids = {new_id() for _ in range(10_000)}
    assert len(ids) == 10_000


def test_new_id_sortable_by_time():
    sample = [new_id() for _ in range(50)]
    assert sample == sorted(sample), "ULIDs generated in sequence should be lexicographically sorted"
