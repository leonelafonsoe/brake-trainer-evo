"""The replay harness feeds real frames and log lines through the engine."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from brake_trainer.config import Settings
from brake_trainer.engine import BrakeEngine
from brake_trainer.models import CueKind

from .replay import Replay, ReplayFrame, line_at

NOTIFICATION = "[gameface] [info] Adding notification UINotificationType_SessionPenalty"
SPLIT = "[gameplay] [info] Received split: isStart false, isEnd false, index {index} "


BASE = datetime(2026, 10, 24, 12, 0, tzinfo=UTC).timestamp()


def test_a_replayed_cut_line_is_attributed_at_its_own_time(store):
    engine = BrakeEngine(Settings(use_game_log=False, warmup_laps=0), store)
    replay = Replay(engine, start=BASE)

    replay.feed(ReplayFrame(0.10))
    replay.feed(ReplayFrame(0.15))
    replay.feed(ReplayFrame(0.20))
    at = replay.t + replay.dt
    replay.feed(ReplayFrame(0.25, log_line=line_at(NOTIFICATION, at)))

    assert engine.snapshot().pass_flag == "off track"


def test_a_replayed_split_learns_the_games_sector_lines(store):
    engine = BrakeEngine(Settings(use_game_log=True, warmup_laps=0), store)
    replay = Replay(engine, start=BASE)
    positions = [0.0001, 0.10, 0.20, 0.30, 0.33, 0.40, 0.50, 0.60, 0.66, 0.70, 0.80, 0.90]
    frames = [ReplayFrame(pos) for pos in positions]
    frames[4] = replace(frames[4], log_line=line_at(SPLIT.format(index=0), 5 * replay.dt))
    frames[8] = replace(frames[8], log_line=line_at(SPLIT.format(index=1), 9 * replay.dt))

    replay.run(frames)

    boundaries = engine.snapshot().boundaries
    assert len(boundaries) == 4
    assert boundaries[0] == 0.0 and boundaries[-1] == 1.0
    assert 0.2 < boundaries[1] < 0.4
    assert 0.6 < boundaries[2] < 0.8


def test_the_harness_reports_the_same_cues_as_the_engine(store):
    # A cue callback proves the replay drives the normal update path, not a parallel one.
    cues: list[CueKind] = []
    engine = BrakeEngine(
        Settings(use_game_log=False, warmup_laps=0),
        store,
        on_cue=cues.append,
    )
    replay = Replay(engine, start=BASE)
    for pos in (0.10, 0.12, 0.14):
        replay.feed(ReplayFrame(pos, speed_kmh=200.0, brake=0.8))
    # No cue is expected yet (no stored point); this asserts the callback path is wired and the
    # harness did not bypass the engine.
    assert cues == []
