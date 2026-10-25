"""Log lines and helpers shared by the game-log test modules."""

from __future__ import annotations

from pathlib import Path

from brake_trainer.gamelog import LogState, parse_line

PLAYER = "0a1b2c3d-1111-2222-3333-444455556666"
AI = "ffffffff-aaaa-bbbb-cccc-000011112222"
CONNECT = (
    "[2026-10-14 21:00:00.100] [network] [info] 76561198000000001 connected (true) on car "
    f"ferrari_296_gtb, with new carId {PLAYER}"
)
AI_CONNECT = (
    f"[2026-10-14 21:00:00.200] [network] [info] 0 connected (false) on car bmw_m4, "
    f"with new carId {AI}"
)
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


def limits(car: str, tyres: int, inside: float) -> str:
    return (
        f"[2026-10-14 21:05:00.000] [physics] [info] Limits: car {car} "
        f"tyres out changed: 3 -> {tyres} with {inside}m inside"
    )


def player_state() -> LogState:
    state = LogState()
    parse_line(CONNECT, state)
    parse_line(AI_CONNECT, state)
    return state
