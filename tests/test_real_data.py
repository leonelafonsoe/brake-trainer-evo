"""Real stored files shared by users: the current loader must still accept them."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from brake_trainer.models import DATA_VERSION, TrackData

FIXTURES = Path(__file__).with_name("fixtures") / "track_data"


@pytest.mark.parametrize(
    ("name", "track", "boundaries", "runs"),
    [
        (
            "circuit_de_spa_francorchamps__ferrari_296_gt3.json",
            "Circuit de Spa Francorchamps",
            (0.3279941976070404, 0.7234436273574829),
            (3, 3, 3),
        ),
        (
            "imola__ferrari_296_gt3.json",
            "Imola",
            (0.30235809087753296, 0.6674477458000183),
            (3, 3, 3),
        ),
        (
            "monza__ferrari_296_gt3.json",
            "Monza",
            (0.33644832163172367, 0.6567313191597194),
            (3, 3, 3),
        ),
        (
            "red_bull_ring__ferrari_296_gt3.json",
            "Red Bull Ring",
            (0.2609367072582245, 0.6577140092849731),
            (2, 1, 2),
        ),
    ],
)
def test_real_stored_track_data_still_loads(store, name, track, boundaries, runs):
    raw = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert raw["version"] == DATA_VERSION
    data = TrackData.from_dict(raw)
    assert data.track == track
    assert data.car == "Ferrari 296 GT3"
    assert data.n_sectors == 3
    assert data.boundaries == pytest.approx(boundaries)
    assert tuple(len(sector) for sector in data.sectors) == runs
    assert data.total_runs() == sum(runs)

    store.save(data)
    assert store.load(track, data.car, 3) == data
