from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path

from brain.storage import paths


def test_brain_dir_reads_from_settings(tmp_brain: Path):
    assert paths.brain_dir() == tmp_brain


def test_raw_path_for_partitions_by_utc_date(tmp_brain: Path):
    when = datetime(2026, 4, 26, 14, 32, 0, tzinfo=timezone.utc)
    p = paths.raw_path_for("01HX", "cold-email", when=when)
    assert p == tmp_brain / "raw" / "2026" / "04" / "26" / "01HX--cold-email.md"


def test_raw_path_for_converts_local_to_utc(tmp_brain: Path):
    # 2026-04-26 23:30 UTC+8 == 2026-04-26 15:30 UTC — same UTC day, but
    # 2026-04-27 02:30 UTC+8 == 2026-04-26 18:30 UTC — also same UTC day.
    # Pick a moment that crosses dates to prove conversion happens.
    plus_eight = timezone(timedelta(hours=8))
    when_local = datetime(2026, 4, 27, 3, 0, 0, tzinfo=plus_eight)  # = 2026-04-26 19:00 UTC
    p = paths.raw_path_for("01HX", "x", when=when_local)
    assert "2026/04/26" in p.as_posix()


def test_raw_path_for_naive_datetime_treated_as_utc(tmp_brain: Path):
    naive = datetime(2026, 4, 26, 14, 32, 0)
    p = paths.raw_path_for("01HX", "x", when=naive)
    assert "2026/04/26" in p.as_posix()


def test_raw_path_for_default_when_uses_now(tmp_brain: Path):
    p = paths.raw_path_for("01HX", "x")
    today_utc = datetime.now(timezone.utc)
    expected_segment = f"{today_utc.year:04d}/{today_utc.month:02d}/{today_utc.day:02d}"
    assert expected_segment in p.as_posix()


def test_inbox_path_for(tmp_brain: Path):
    assert paths.inbox_path_for("01HX", "abc") == tmp_brain / "inbox" / "01HX--abc.md"


def test_meta_paths(tmp_brain: Path):
    assert paths.index_path() == tmp_brain / "INDEX.md"
    assert paths.log_path() == tmp_brain / "LOG.md"
    assert paths.schema_path() == tmp_brain / "SCHEMA.md"
