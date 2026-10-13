"""The overlay's status line: the most relevant thing happening right now."""

from __future__ import annotations

from ..config import Settings
from ..models import SectorStatus, Snapshot
from . import theme

RESULT_SHOW_S = 6.0  # how long a finished sector's result stays on screen

_WORDS = {SectorStatus.BEST: "best", SectorStatus.GOOD: "good", SectorStatus.SLOWER: "slower"}
_QUIET_NOTES = ("warm-up", "surveying")  # results that only repeat the warm-up message


def status_line(snap: Snapshot, settings: Settings, live: bool) -> tuple[str, str] | None:
    """(text, colour) for the line under the sector bar, or None when there is nothing to say.

    Priority: the current sector can't count > learning paused > warm-up > the last sector
    result (for a few seconds) > borrowed reference > a quiet summary of what is learned.
    """
    if not live:
        return None
    if snap.pass_flag and snap.sector is not None:
        return (f"S{snap.sector + 1} won't count · {snap.pass_flag}", theme.RED)
    if not settings.learning_enabled:
        return ("Learning paused", theme.AMBER)
    if snap.warming_up:
        return ("Warm-up lap · not learning", theme.AMBER)

    result = snap.last_result
    if result is not None and snap.last_result_age is not None:
        recent = snap.last_result_age < RESULT_SHOW_S
        quiet = result.duration is None and any(q in result.note for q in _QUIET_NOTES)
        if recent and not quiet:
            label = f"S{result.sector + 1}"
            if result.duration is None:
                return (f"{label} {result.note}", theme.AMBER)
            word = _WORDS.get(result.status, "")
            colour = theme.STATUS_COLORS.get(result.status, theme.TEXT_DIM)
            return (f"{label} {result.duration:.2f} s · {word}", colour)

    if snap.reference_car and snap.reference_sectors:
        return (f"Reference: {snap.reference_car}", theme.AMBER)
    n = len(snap.zones)
    if not n:
        return ("No braking points yet", theme.TEXT_DIM)
    note = " · equal sector lines" if snap.equal_lines else ""
    return (f"{n} braking points{note}", theme.TEXT_DIM)
