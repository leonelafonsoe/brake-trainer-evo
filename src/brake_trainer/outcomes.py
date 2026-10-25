"""Typed sector outcomes and the one place their words live.

The engine works in :class:`~brake_trainer.models.DropReason` values; only the driver-facing text
is built here. Keeping the phrases out of the learning logic means a reason cannot be silently
lost to a typo in a string comparison, and the status line can ask a result whether it is quiet
without matching English substrings.
"""

from __future__ import annotations

from .models import DropReason, OutcomeKind, SectorOutcome

# Flags shown on the overlay for the sector in progress (in priority order).
PASS_FLAGS = (DropReason.LAP_INVALIDATED, DropReason.OFF_TRACK)

# Reasons a pass cannot count that say nothing about the sector bar: the lap is a warm-up one, or it
# was driven while the sector lines were still being found or had just changed under the car. The
# status line already says so, and a flag on top of it would read as if it were the reason.
NOT_COUNTING_ANYWAY = (DropReason.WARM_UP, DropReason.FINDING_LINES)

# The reasons a pass may carry and still have its braking points kept (see TrackData.early_onsets).
LINES_REASONS = frozenset({DropReason.FINDING_LINES, DropReason.LINES_MOVED})

# When several reasons apply to the same sector, name the one that explains it best. A result note
# with every reason reads like a stack trace, and the later ones add nothing the driver needs.
PRIORITY = (
    DropReason.WARM_UP,
    DropReason.FINDING_LINES,
    DropReason.LINES_MOVED,
    DropReason.OFF_TRACK,
    DropReason.LAP_INVALIDATED,
    DropReason.PIT_RESET_PARTIAL,
    DropReason.PAUSED,
    DropReason.COVERAGE,
)

_WORDS = {
    DropReason.WARM_UP: "warm-up lap",
    DropReason.FINDING_LINES: "finding the sector lines",
    DropReason.LINES_MOVED: "the lines were learned mid-sector",
    DropReason.PIT_RESET_PARTIAL: "pit, reset or partial",
    DropReason.PAUSED: "learning was paused",
    DropReason.OFF_TRACK: "off track",
    DropReason.LAP_INVALIDATED: "lap invalidated",
}

_ACCEPTED_WORDS = {
    OutcomeKind.KEPT: "kept",
    OutcomeKind.WOULD_KEEP: "would be kept",
    OutcomeKind.NOT_KEPT: "not kept",
}


def primary(reasons: set[DropReason]) -> DropReason:
    """The one reason worth showing for a sector that did not count."""
    for reason in PRIORITY:
        if reason in reasons:
            return reason
    # An unexpected reason cannot come from the engine, but render something stable rather than
    # crashing on a set that is not empty.
    if not reasons:
        raise ValueError("a dropped sector needs at least one reason")
    return min(reasons, key=lambda reason: reason.value)


def render_reason(reason: DropReason, detail: str = "") -> str:
    """The driver-facing phrase for one reason (and its detail, when it has one)."""
    if reason is DropReason.COVERAGE:
        return f"{detail} covered".strip()
    return _WORDS[reason]


def render_outcome(outcome: SectorOutcome) -> str:
    """The result note for an outcome: "kept", or "not counted · <why>"."""
    if outcome.kind is not OutcomeKind.DROPPED:
        return _ACCEPTED_WORDS[outcome.kind]
    reason = outcome.reason
    if reason is None:  # the engine always sets one; do not crash on a hand-built outcome
        return "not counted"
    return f"not counted · {render_reason(reason, outcome.detail)}"


def pass_flag_text(reason: DropReason | None) -> str:
    """The overlay's pass flag, or "" when the sector needs none."""
    return "" if reason is None else render_reason(reason)
