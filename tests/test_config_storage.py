from __future__ import annotations

import errno
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from brake_trainer import __version__
from brake_trainer import config as config_module
from brake_trainer import fileio as fileio_module
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
    path.write_text(
        json.dumps(
            {
                "settings_version": SETTINGS_VERSION,
                "volume": 7,
                "lead_s": "fast",
                "bogus": 1,
                "top_runs": True,
            }
        )
    )
    st = load_settings(path)
    assert st.volume == 1.0
    assert st.lead_s == Settings().lead_s
    assert st.top_runs == Settings().top_runs


def test_settings_missing_or_corrupt_file(tmp_path):
    assert load_settings(tmp_path / "nope.json") == Settings()
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert load_settings(bad) == Settings()


def test_a_corrupt_settings_file_is_moved_aside_not_overwritten(tmp_path):
    path = tmp_path / "settings.json"
    original = "{not json"
    path.write_text(original, encoding="utf-8")

    assert load_settings(path) == Settings()

    assert not path.exists()
    archived = list(tmp_path.glob("settings.invalid-*.json"))
    assert len(archived) == 1
    assert archived[0].read_text(encoding="utf-8") == original


def test_settings_are_never_written_when_the_unreadable_file_cannot_be_moved(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    original = "{not json"
    path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(config_module, "_archive_settings", lambda _path, _reason: False)

    assert load_settings(path) == Settings()
    assert not save_settings(Settings(volume=0.2), path)
    assert path.read_text(encoding="utf-8") == original


def test_non_finite_settings_fall_back_to_the_default():
    assert Settings.from_dict({"volume": float("nan"), "lead_s": float("inf")}) == Settings()
    assert Settings(volume=float("nan")).clamped().volume == Settings().volume


@pytest.mark.parametrize("version", [SETTINGS_VERSION - 1, SETTINGS_VERSION + 1])
def test_a_settings_file_from_another_version_is_archived_not_migrated(tmp_path, version):
    # There is no per-version migration: a layout this build does not know is kept as evidence and
    # the app starts from defaults.
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"settings_version": version, "volume": 0.4}), encoding="utf-8")

    assert load_settings(path) == Settings()

    assert not path.exists()
    archived = list(tmp_path.glob("settings.version-*.json"))
    assert len(archived) == 1
    assert json.loads(archived[0].read_text(encoding="utf-8"))["volume"] == 0.4


def test_the_real_0_3_11_settings_file_is_archived(tmp_path):
    # The shared 0.3.11 file predates `settings_version` and stores retired keys. It is evidence of
    # the old layout, so it is moved aside intact rather than partly loaded.
    original = (FIXTURES / "settings_0.3.11.json").read_text(encoding="utf-8")
    path = tmp_path / "settings.json"
    path.write_text(original, encoding="utf-8")

    assert load_settings(path) == Settings()

    archived = list(tmp_path.glob("settings.version-0-*.json"))
    assert len(archived) == 1
    assert archived[0].read_text(encoding="utf-8") == original


def test_save_settings_reports_a_failed_write(tmp_path):
    path = tmp_path / "settings.json"
    path.mkdir()  # replacing a file with a directory must fail
    assert not save_settings(Settings(), path)
    assert not list(tmp_path.glob("*.tmp"))  # the temporary file is not left behind


def test_a_failed_settings_fsync_keeps_the_old_file_and_removes_the_temporary(
    tmp_path, monkeypatch
):
    path = tmp_path / "settings.json"
    assert save_settings(Settings(volume=0.2), path)
    original = path.read_text(encoding="utf-8")

    def full(*args, **kwargs):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(fileio_module.os, "fsync", full)
    assert not save_settings(Settings(volume=0.9), path)

    assert path.read_text(encoding="utf-8") == original
    assert not list(tmp_path.glob("*.tmp"))


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


def test_runs_are_sorted_fastest_first_on_load():
    raw = _data("Car A", 2, 18.0).to_dict()
    raw["sectors"][0].reverse()

    data = TrackData.from_dict(raw)

    assert [run.t for run in data.sectors[0]] == [18.0, 19.0]


@pytest.mark.parametrize(
    "run",
    [
        {"t": 0.0, "onsets": []},
        {"t": -1.0, "onsets": []},
        {"t": float("nan"), "onsets": []},
        {"t": 18.0, "onsets": [1.5]},
        {"t": 18.0, "onsets": [-0.1]},
        {"t": 18.0, "onsets": [float("inf")]},
        {"t": 18.0, "onsets": "nope"},
    ],
)
def test_a_malformed_run_is_refused(run):
    raw = _data("Car A", 1).to_dict()
    raw["sectors"][0] = [run]

    with pytest.raises(ValueError):
        TrackData.from_dict(raw)


def test_a_bad_run_is_quarantined_instead_of_used(store):
    raw = _data("Car A", 1).to_dict()
    raw["sectors"][0][0]["t"] = 0.0
    path = store.directory / "Monza__Car_A.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw), encoding="utf-8")

    assert store.load("Monza", "Car A", 3).total_runs() == 0
    assert not path.exists()
    assert list(store.quarantine_directory.glob("Monza__Car_A.corrupt-*.json"))


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
    refused = store.apply(DeleteSector("Monza", "Car A", 0))
    assert not refused.ok and not refused.changed  # a refusal, not a successful no-op
    assert refused.detail
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

    monkeypatch.setattr(fileio_module.os, "replace", refuse)
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

    monkeypatch.setattr(fileio_module.os, "fsync", full)
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


def test_an_edit_for_an_entry_that_was_never_stored_is_a_successful_no_op(store):
    result = store.apply(DeleteSector("Monza", "Never driven", 0))
    assert result.ok and not result.changed and not result.detail


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


def test_a_legacy_name_is_resolved_only_once_per_identity(store, monkeypatch):
    # Every sector close saves. Now that a legacy file is read to check whose it is, that read must
    # happen when the name is resolved, not on every save.
    write_path = _data("Car A", 1, 18.0)
    legacy = store.directory / "Monza__Car_A.json"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(json.dumps(write_path.to_dict()), encoding="utf-8")

    calls: list[Path] = []
    original = store._stored_names
    monkeypatch.setattr(store, "_stored_names", lambda p: calls.append(p) or original(p))

    assert store.save(_data("Car A", 2, 19.0))
    assert store.save(_data("Car A", 3, 20.0))

    assert calls == [legacy]


def test_deleting_an_entry_forgets_its_resolved_path(store):
    assert store.save(_data("Car A", 1))
    assert store.delete("Monza", "Car A").changed
    assert store.load("Monza", "Car A", 3).total_runs() == 0

    assert store.save(_data("Car A", 2))
    assert store.load("Monza", "Car A", 3).total_runs() == 2


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

    # The row that is still there is named by its own onsets.
    assert store.apply(DeleteRun("Monza", "Car A", 0, 18.0, (0.05,))).changed
    assert store.load("Monza", "Car A", 3).sectors[0] == []


def test_a_snapshot_summarises_entries_and_issues(store):
    data = _data("Car A", 2, 18.0)
    data.boundaries = [0.3, 0.6]
    assert store.save(data)

    snapshot = store.snapshot()

    assert len(snapshot.entries) == 1
    entry = snapshot.entries[0]
    assert (entry.track, entry.car, entry.n_sectors, entry.game_lines) == (
        "Monza",
        "Car A",
        3,
        True,
    )
    assert entry.total_runs() == 2
    assert entry.sectors[0][0].time == 18.0
    assert entry.sectors[0][0].onsets == (0.1,)
    assert snapshot.issues == ()

    (store.directory / "junk.json").write_text("nope", encoding="utf-8")
    snapshot = store.snapshot()
    assert len(snapshot.issues) == 1  # the scan itself reports the file it moved aside


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
