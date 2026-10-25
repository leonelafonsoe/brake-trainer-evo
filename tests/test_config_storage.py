from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from brake_trainer import __version__
from brake_trainer.buildinfo import build_id
from brake_trainer.config import SETTINGS_VERSION, Settings, load_settings, save_settings
from brake_trainer.models import DATA_VERSION, SectorRun, TrackData
from brake_trainer.storage import DeleteSector, LoadStatus

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
