from __future__ import annotations

import json

from brake_trainer.config import Settings, load_settings, save_settings
from brake_trainer.models import SectorRun, TrackData


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


def test_old_settings_get_the_games_give_back_window_once():
    # Version 1 stored the old default of 0, which put a cut in the sector the report landed in.
    # It must be moved to the game's 500 m window, but a deliberate 0 written since must stay 0.
    old = Settings.from_dict({"cut_give_back_m": 0.0})
    assert old.cut_give_back_m == 500.0
    assert old.settings_version == 2

    current = Settings.from_dict({"settings_version": 2, "cut_give_back_m": 0.0})
    assert current.cut_give_back_m == 0.0


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


def test_store_roundtrip_and_layout_mismatch(store):
    store.save(_data("Car A", 2))
    assert store.load("Monza", "Car A", 3).total_runs() == 2
    assert store.load("Monza", "Car A", 5).total_runs() == 0  # different sector count


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
    (store.directory / "junk.json").write_text("nope")
    assert len(store.entries()) == 2
    assert store.delete("Monza", "A")
    assert store.clear() == 1
