"""Constants shared by the braking-point learning engine.

Kept in a leaf module so every part of the package can read them without an import cycle.
"""

from __future__ import annotations

DEFAULT_LENGTH_M = 5000.0
_COVERAGE_REQUIRED = 0.9  # share of a sector that must be driven for it to count

# The game scores every lap in three sectors and shows three splits. The app uses the same three,
# so its sectors are the ones the game reports; only the two inner lines have to be found, which is
# what the game's split lines in its log are for.
N_SECTORS = 3
# A log that never brings a split (following it is off, or this build does not write them) would
# otherwise leave every lap uncounted, so the equal splits are settled for after this many laps.
_LINES_WAIT_LAPS = 3
# A pass in progress when the lines are learned is only kept if it began on a line that both
# layouts share (in practice the start/finish line). This is how close its start has to be to one:
# a few metres of lap, far inside the gap between an equal split and the game's own line.
_LINE_MATCH = 0.001

# Flags shown on the overlay for the sector in progress (in priority order).
_PASS_FLAGS = ("lap invalidated", "off track")

# Reasons a pass cannot count that say nothing about the sector bar: the lap is a warm-up one, or it
# was driven while the sector lines were still being found or had just changed under the car. The
# status line already says so, and a flag on top of it would read as if it were the reason.
_NOT_COUNTING_ANYWAY = ("warm-up lap", "finding the sector lines")

# When several reasons apply to the same sector, name the one that explains it best. A result note
# with every reason reads like a stack trace, and the later ones add nothing the driver needs.
_NOTE_PRIORITY = (
    "warm-up lap",
    "finding the sector lines",
    "the lines were learned mid-sector",
    "off track",
    "lap invalidated",
)

# The reasons a pass may carry and still have its braking points kept (see TrackData.early_onsets).
_LINES_REASONS = frozenset({"finding the sector lines", "the lines were learned mid-sector"})

# How much of the recent sample history to keep, so a cut can be attributed from the position the
# car had when the game wrote the line. The game buffers its log (a few KB, flushed when full), so a
# cut can be read a whole lap after it was judged, so this covers a lap or two of driving at any
# sane rate.
_HISTORY_S = 300.0

# Shown when the game invalidates a lap that the app saw no off-track for (no race cut and no cut
# in its log): the game judged it from something it does not expose per violation, so the sector it
# happened in cannot be identified.
_CUT_WARNING = (
    "The game invalidated the lap with no race cut and no cut in its log, so the sector it "
    "happened in cannot be identified: only the sector where the flag dropped will be dropped."
)
