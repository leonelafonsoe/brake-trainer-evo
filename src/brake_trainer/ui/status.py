"""The overlay's status line: the most relevant thing happening right now."""

from __future__ import annotations

from ..config import Settings
from ..models import SectorStatus, Snapshot
from . import theme

RESULT_SHOW_S = 6.0  # how long a finished sector's result stays on screen
LATE_CUT_SHOW_S = 12.0  # how long a cut reported for a lap that is already gone stays on screen

_WORDS = {SectorStatus.BEST: "best", SectorStatus.GOOD: "good", SectorStatus.SLOWER: "slower"}
_QUIET_NOTES = ("warm-up", "finding the sector lines")  # only repeat the status line above


def phase_label(snap: Snapshot, settings: Settings) -> str:
    """The word in the big distance readout while there is no braking point to show yet.

    It used to say "learning…" whenever the readout was empty - including while the app was waiting
    for the game's sector lines, or sitting in a warm-up lap, when it is not learning at all.
    Learning only starts once the warm-up laps are done *and* the game's lines are known; until
    then, say which of those it is.
    """
    if not settings.learning_enabled:
        return "paused"
    if snap.warmup_laps_left:
        return "warm-up"
    if snap.warming_up:
        return "waiting…"
    return "learning…"


def status_line(
    snap: Snapshot, settings: Settings, live: bool, error: str = ""
) -> tuple[str, str] | None:
    """(text, colour) for the line under the sector bar, or None when there is nothing to say.

    Priority: a telemetry failure > a cut reported for a lap that is already gone > the current
    sector can't count > learning paused > warm-up or waiting for the game's sector lines > the last
    sector result (for a few seconds) > borrowed reference > a quiet summary of what is learned.
    """
    if error:
        # A failure has to be visible even when no sample is arriving: that is exactly when it
        # matters, and the overlay would otherwise just say it is waiting.
        return (error, theme.RED)
    if not live:
        return None
    if snap.storage_warning:
        # A learned-data file could not be read. The Data tab has the path and the reason; this
        # line only needs to stop the driver wondering why the entry looks empty.
        return (snap.storage_warning, theme.RED)
    if snap.late_cut and snap.late_cut_age is not None and snap.late_cut_age < LATE_CUT_SHOW_S:
        # The sector bar has moved on to another lap, so this is the only place it can appear.
        return (snap.late_cut, theme.RED)
    if snap.pass_flag and snap.sector is not None:
        return (f"S{snap.sector + 1} won't count · {snap.pass_flag}", theme.RED)
    if not settings.learning_enabled:
        return ("Learning paused", theme.AMBER)
    if snap.warmup_laps_left:
        return ("Warm-up lap · not learning", theme.AMBER)
    if snap.warming_up:
        # Nothing is being learned yet, and that is not up to the driver: the game has not said
        # where its own sector lines are yet. Calling that "learning" made the wait look like a
        # problem to fix.
        return ("Waiting for the game's sector lines", theme.AMBER)

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
            delta = "" if result.delta is None else f" ({result.delta:+.2f} s)"
            return (f"{label} {result.duration:.2f} s · {word}{delta}", colour)

    if snap.reference_car and snap.reference_sectors:
        return (f"Reference: {snap.reference_car}", theme.AMBER)
    n = len(snap.zones)
    if not n:
        return ("No braking points yet", theme.TEXT_DIM)
    note = " · equal sector lines" if snap.equal_lines else ""
    return (f"{n} braking points{note}", theme.TEXT_DIM)
