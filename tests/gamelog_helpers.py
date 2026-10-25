"""Log lines and helpers shared by the game-log test modules."""

from __future__ import annotations

from pathlib import Path

# One HUD notification per cut, written when the game judges it (build 0.5+).
NOTIFICATION = (
    "[2026-10-16 20:41:38.703] [gameface] [info] "
    "Adding notification UINotificationType_SessionPenalty "
)
# The end of one of the game's three sectors, written the moment the car crosses its line.
SPLIT = (
    "[2026-10-16 20:41:00.000] [gameplay] [info] "
    "Received split: isStart false, isEnd false, index 1 "
)
# Real build 0.9.1 excerpts; see tests/fixtures/game_log/README.md.
FIXTURES = Path(__file__).with_name("fixtures") / "game_log"
