from __future__ import annotations

import errno
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest

from brake_trainer import __version__
from brake_trainer import storage as storage_module
from brake_trainer.buildinfo import build_id
from brake_trainer.config import SETTINGS_VERSION, Settings, load_settings, save_settings
from brake_trainer.models import DATA_VERSION, SectorRun, TrackData
from brake_trainer.storage import DeleteRun, DeleteSector, LoadStatus, StoreResult

FIXTURES = Path(__file__).with_name("fixtures") / "settings"


def test_settings_roundtrip(tmp_path):
    path = tmp_path / "s.json"
    original = Settings(volume=0.3, overlay_x=120, warmup_laps=2, reference_car="296")
    save_settings(original, path)
    assert load_settings(path) == original


def test_settings_ignore_bad_values_and_clamp(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"volume": 7, "lead_s": "fast", "bogus": 1, "top_runs": True}))
    st = load_settings(path)
    assert st.volume == 1.0
    assert st.lead_s == Settings().lead_s
    assert st.top_runs == Settings().top_runs


def test_settings_missing_or_corrupt_file(tmp_path):
    assert load_settings(tmp_path / "nope.json") == Settings()
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert load_settings(bad) == Settings()


def test_a_retired_setting_is_ignored_and_the_version_advances():
    # Version 2 stored `cut_give_back_m`; version 3 trusts each event's own position instead. The
    # key is now unknown and ignored, and the file is written back without it.
    st = Settings.from_dict({"settings_version": 2, "cut_give_back_m": 500.0, "volume": 0.4})
    assert st.settings_version == SETTINGS_VERSION
    assert st.volume == 0.4
    assert "cut_give_back_m" not in st.to_dict()


def test_the_real_0_3_11_settings_migrate_once(tmp_path):
    # The shared 0.3.11 file has no version and stores the retired cut setting.
    path = tmp_path / "settings.json"
    path.write_text(
        (FIXTURES / "settings_0.3.11.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    st = load_settings(path)
    assert st.settings_version == SETTINGS_VERSION
    assert st.volume == 0.6  # the rest of the real file is kept
    assert st.debug_logging is True

    save_settings(st, path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["settings_version"] == SETTINGS_VERSION
    assert "cut_give_back_m" not in raw  # the retired key is not written again


def test_a_newer_settings_file_is_kept_and_warned_about(caplog):
    # A file written by a newer build must not be rewritten with this build's version: that would
    # make the next run migrate it again and lose whatever the newer build chose.
    raw = {"settings_version": SETTINGS_VERSION + 1, "volume": 0.4}
    with caplog.at_level(logging.WARNING, logger="brake_trainer.config"):
        st = Settings.from_dict(raw)
    assert st.settings_version == SETTINGS_VERSION + 1
    assert st.volume == 0.4
    assert any("newer version" in record.message for record in caplog.records)


def test_a_newer_settings_file_keeps_unknown_keys_on_save(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "settings_version": SETTINGS_VERSION + 1,
                "volume": 0.4,
                "future_option": {"nested": True},
            }
        ),
        encoding="utf-8",
    )

    st = load_settings(path)
    assert st.volume == 0.4
    assert st.settings_version == SETTINGS_VERSION + 1
    assert save_settings(st, path)

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["settings_version"] == SETTINGS_VERSION + 1
    assert saved["future_option"] == {"nested": True}
    assert saved["volume"] == 0.4


def test_save_settings_reports_a_failed_write(tmp_path):
    path = tmp_path / "settings.json"
    path.mkdir()  # replacing a file with a directory must fail
    assert not save_settings(Settings(), path)


def test_brake_off_stays_below_brake_on():
    st = Settings(brake_on=0.2, brake_off=0.5).clamped()
    assert st.brake_off < st.brake_on


def test_verbose_logging_is_off_by_default_and_round_trips(tmp_path):
    assert Settings().debug_logging is False
    path = tmp_path / "s.json"
    save_settings(Settings(debug_logging=True), path)
    assert load_settings(path).debug_logging is True


def _data(car: str, runs: int, t: float = 30.0) -> TrackData:
    d = TrackData.empty("Monza", car, 3)
    for i in range(runs):
        d.sectors[0].append(SectorRun(t + i, [0.1]))
    return d


def test_saved_files_carry_the_app_version_build_and_save_time(tmp_path, store):
    path = tmp_path / "settings.json"
    save_settings(Settings(volume=0.2), path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["app_version"] == __version__
    assert raw["build"] == build_id()
    assert raw["saved_at"].endswith("+00:00")
    assert raw["volume"] == 0.2

    store.save(_data("Car A", 1))
    raw_data = json.loads((store.directory / "Monza__Car_A.json").read_text(encoding="utf-8"))
    assert raw_data["app_version"] == __version__
    assert raw_data["build"] == build_id()
    assert raw_data["saved_at"].endswith("+00:00")
    assert raw_data["version"] == DATA_VERSION  # the data format version is still its own field


def test_a_newer_data_version_is_refused():
    # The app version in a file is provenance, but the data format version gates how the runs may
    # be read: a newer layout must not be filed under this build's boundaries.
    raw = _data("Car A", 1).to_dict()
    raw["version"] = DATA_VERSION + 1
    with pytest.raises(ValueError, match="newer"):
        TrackData.from_dict(raw)


def test_store_quarantines_a_newer_data_file(store):
    path = store.directory / "Monza__Car_A.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = _data("Car A", 1).to_dict()
    raw["version"] = DATA_VERSION + 1
    original = json.dumps(raw)
    path.write_text(original, encoding="utf-8")

    assert store.load("Monza", "Car A", 3).total_runs() == 0
    assert not path.exists()  # the newer file was moved, not overwritten
    quarantined = list(store.quarantine_directory.glob("Monza__Car_A.newer-*.json"))
    assert len(quarantined) == 1
    assert quarantined[0].read_text(encoding="utf-8") == original

    issues = store.take_issues()
    assert len(issues) == 1
    assert issues[0].status is LoadStatus.NEWER
    assert issues[0].quarantine_path == quarantined[0]
    assert not issues[0].blocked
    assert store.take_issues() == []  # reported once


def test_store_quarantines_corrupt_and_layout_mismatch(store):
    junk = store.directory / "junk.json"
    junk.parent.mkdir(parents=True, exist_ok=True)
    junk.write_text("nope", encoding="utf-8")
    assert store.entries() == []
    assert not junk.exists()
    assert list(store.quarantine_directory.glob("junk.corrupt-*.json"))

    store.save(_data("Car A", 2))
    assert store.load("Monza", "Car A", 5).total_runs() == 0  # different sector count
    assert not (store.directory / "Monza__Car_A.json").exists()
    assert list(store.quarantine_directory.glob("Monza__Car_A.layout_mismatch-*.json"))


def test_store_blocks_saves_when_quarantine_fails(store, monkeypatch):
    path = store.directory / "Monza__Car_A.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = _data("Car A", 1).to_dict()
    raw["version"] = DATA_VERSION + 1
    original = json.dumps(raw)
    path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(store, "_quarantine", lambda path, status: None)

    assert store.load("Monza", "Car A", 3).total_runs() == 0
    assert path.read_text(encoding="utf-8") == original  # still in place
    assert not store.save(_data("Car A", 2))  # refused: the path is blocked
    assert path.read_text(encoding="utf-8") == original
    issue = store.issues()[0]
    assert issue.blocked
    assert issue.quarantine_path is None


def test_store_apply_does_not_overwrite_an_unsafe_file(store, monkeypatch):
    path = store.directory / "Monza__Car_A.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = _data("Car A", 1).to_dict()
    raw["version"] = DATA_VERSION + 1
    original = json.dumps(raw)
    path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(store, "_quarantine", lambda path, status: None)

    store.load("Monza", "Car A", 3)  # blocks the path
    assert not store.apply(DeleteSector("Monza", "Car A", 0))
    assert path.read_text(encoding="utf-8") == original


def test_share_lines_does_not_overwrite_an_unsafe_entry(store, monkeypatch):
    target = store.directory / "Monza__Car_B.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    raw = _data("Car B", 1).to_dict()
    raw["version"] = DATA_VERSION + 1
    original = json.dumps(raw)
    target.write_text(original, encoding="utf-8")

    other = _data("Car A", 0)
    other.boundaries = [0.3, 0.6]
    assert store.save(other)
    monkeypatch.setattr(store, "_quarantine", lambda path, status: None)

    data = store.load("Monza", "Car B", 3)  # blocks the target
    assert store.share_lines(data) == ""
    assert target.read_text(encoding="utf-8") == original


def test_a_failed_replace_keeps_the_old_file_and_removes_the_temporary(store, monkeypatch):
    store.save(_data("Car A", 1))
    path = store.directory / "Monza__Car_A.json"
    original = path.read_text(encoding="utf-8")

    def refuse(*args, **kwargs):
        raise OSError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(storage_module.os, "replace", refuse)
    result = store.save(_data("Car A", 2))

    assert not result.ok and not result.changed
    assert "Permission denied" in result.detail
    assert path.read_text(encoding="utf-8") == original  # the previous entry survives
    assert not list(store.directory.glob("*.tmp"))  # and nothing is left behind


def test_a_full_disk_is_reported_and_the_temporary_file_is_removed(store, monkeypatch):
    store.save(_data("Car A", 1))
    path = store.directory / "Monza__Car_A.json"
    original = path.read_text(encoding="utf-8")

    def full(*args, **kwargs):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(storage_module.os, "fsync", full)
    result = store.save(_data("Car A", 2))

    assert not result.ok and not result.changed
    assert "No space left" in result.detail
    assert path.read_text(encoding="utf-8") == original
    assert not list(store.directory.glob("*.tmp"))


def test_an_edit_that_cannot_be_written_is_a_failure_not_a_no_op(store, monkeypatch):
    store.save(_data("Car A", 1))
    monkeypatch.setattr(
        store, "save", lambda data: StoreResult(ok=False, detail="No space left on device")
    )

    failed = store.apply(DeleteSector("Monza", "Car A", 0))

    assert not failed.ok and not failed.changed
    assert "No space" in failed.detail
    # Nothing to delete is still a successful no-op, and the two must not look alike.
    monkeypatch.undo()
    no_op = store.apply(DeleteSector("Monza", "Car A", 2))
    assert no_op.ok and not no_op.changed


def test_a_delete_that_cannot_remove_the_file_is_reported(store):
    # The path is a directory, so unlink fails with a real OSError rather than a mocked one.
    (store.directory / "Monza__Car_A.json").mkdir(parents=True)

    result = store.delete("Monza", "Car A")

    assert not result.ok and not result.changed
    assert result.detail


def test_quarantine_never_overwrites_an_earlier_file(store, monkeypatch):
    # Two files quarantined in the same second would otherwise get the same name, and the second
    # move would replace the first one's evidence. The counter keeps both.
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 24, 12, 0, 0, tzinfo=UTC)

    monkeypatch.setattr(storage_module, "datetime", FrozenDatetime)
    path = store.directory / "Monza__Car_A.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    folder = store.quarantine_directory
    folder.mkdir(parents=True, exist_ok=True)
    earlier = folder / "Monza__Car_A.corrupt-20261024-120000.json"
    earlier.write_text("the first one", encoding="utf-8")

    store.load("Monza", "Car A", 3)

    assert earlier.read_text(encoding="utf-8") == "the first one"
    assert {p.name for p in folder.glob("Monza__Car_A.corrupt-*")} == {
        "Monza__Car_A.corrupt-20261024-120000.json",
        "Monza__Car_A.corrupt-20261024-120000-1.json",
    }


def test_two_names_that_slug_the_same_do_not_share_a_file(store):
    # "Car A" and "Car/A" both become Car_A. The second identity must not overwrite the first.
    assert store.save(_data("Car A", 1, 18.0))
    assert store.save(_data("Car/A", 2, 19.0))

    files = sorted(path.name for path in store.directory.glob("*.json"))
    assert len(files) == 2
    assert any("--" in name for name in files)  # the colliding identity got a hash suffix
    assert store.load("Monza", "Car A", 3).total_runs() == 1
    assert store.load("Monza", "Car/A", 3).total_runs() == 2
    assert {(d.track, d.car) for d in store.entries()} == {
        ("Monza", "Car A"),
        ("Monza", "Car/A"),
    }

    assert store.delete("Monza", "Car/A").changed
    assert store.load("Monza", "Car A", 3).total_runs() == 1
    assert store.load("Monza", "Car/A", 3).total_runs() == 0


def test_a_slug_collision_is_resolved_in_either_save_order(store):
    assert store.save(_data("Car/A", 2, 19.0))
    assert store.save(_data("Car A", 1, 18.0))

    assert store.load("Monza", "Car/A", 3).total_runs() == 2
    assert store.load("Monza", "Car A", 3).total_runs() == 1


def test_an_existing_slug_named_file_still_loads_and_is_updated_in_place(store):
    legacy = store.directory / "Monza__Car_A.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(json.dumps(_data("Car A", 1, 18.0).to_dict()), encoding="utf-8")

    assert store.load("Monza", "Car A", 3).total_runs() == 1

    assert store.save(_data("Car A", 2, 19.0))
    assert legacy.exists()  # no migration, no orphaned duplicate
    assert not list(store.directory.glob("*--*.json"))
    assert store.load("Monza", "Car A", 3).total_runs() == 2


def test_deleting_a_run_with_a_duplicate_time_removes_the_named_one(store):
    data = TrackData.empty("Monza", "Car A", 3)
    data.sectors[0] = [SectorRun(18.0, [0.05]), SectorRun(18.0, [0.07])]
    assert store.save(data)

    # The onsets name the row; the time alone would match both.
    assert store.apply(DeleteRun("Monza", "Car A", 0, 18.0, (0.07,))).changed
    remaining = store.load("Monza", "Car A", 3).sectors[0]
    assert [(run.t, run.onsets) for run in remaining] == [(18.0, [0.05])]

    # A stale request for the row that is gone must not fall back to the other one.
    assert not store.apply(DeleteRun("Monza", "Car A", 0, 18.0, (0.99,))).changed
    assert len(store.load("Monza", "Car A", 3).sectors[0]) == 1

    # The old time-only form still works for callers that predate the onsets.
    assert store.apply(DeleteRun("Monza", "Car A", 0, 18.0)).changed
    assert store.load("Monza", "Car A", 3).sectors[0] == []


def test_store_roundtrip(store):
    store.save(_data("Car A", 2))
    assert store.load("Monza", "Car A", 3).total_runs() == 2


def test_store_reference_selection(store):
    store.save(_data("Ferrari 296", 3))
    store.save(_data("BMW M4", 1))
    store.save(_data("Other", 2))
    ref = store.find_reference("Monza", "New Car", 3)
    assert ref is not None and ref.car == "Ferrari 296"  # most data wins
    named = store.find_reference("Monza", "New Car", 3, preferred="bmw")
    assert named is not None and named.car == "BMW M4"
    # A preferred car that is not stored falls back to the best entry instead of returning nothing.
    missing = store.find_reference("Monza", "New Car", 3, preferred="porsche")
    assert missing is not None and missing.car == "Ferrari 296"
    assert store.find_reference("Spa", "New Car", 3) is None
    assert store.find_reference("Monza", "Ferrari 296", 3).car != "Ferrari 296"


def test_store_delete_clear_and_corrupt_files(store):
    store.save(_data("A", 1))
    store.save(_data("B", 1))
    junk = store.directory / "junk.json"
    junk.write_text("nope", encoding="utf-8")
    assert len(store.entries()) == 2
    assert not junk.exists()  # corrupt files are quarantined, not silently ignored
    assert list(store.quarantine_directory.glob("junk.corrupt-*.json"))
    assert store.delete("Monza", "A")
    assert store.clear() == 1


def test_deleting_an_entry_that_is_already_gone_is_a_successful_no_op(store):
    result = store.delete("Monza", "Never driven")

    assert result.ok and not result.changed
    assert not result.detail
