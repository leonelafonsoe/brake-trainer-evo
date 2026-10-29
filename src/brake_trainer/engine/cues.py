"""Braking events and the cues they produce."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..models import CueKind, Sample

if TYPE_CHECKING:
    from .state import EngineState

# Braking ends this far below the start threshold. The same 0.15 gap the old two-setting pair
# defaulted to (0.25 start / 0.10 release), without asking the driver to keep two numbers in step.
_BRAKE_HYSTERESIS = 0.15
_MIN_LEAD_M = 35.0  # at very low speed the warning never comes closer than this


@dataclass(slots=True)
class _BrakeEvent:
    pos: float
    speed: float
    peak: float
    counted: bool = False


class CuesMixin:
    # The full shared state lives in state.py; this keeps the type this mixin assigns explicit.
    _event: _BrakeEvent | None

    def _track_braking(self: EngineState, s: Sample, pos: float) -> None:
        st = self._settings
        if not self._braking and s.brake >= st.brake_threshold:
            self._braking = True
            self._event = _BrakeEvent(pos, s.speed_kmh, s.brake)
        elif self._braking and self._event is not None:
            e = self._event
            e.peak = max(e.peak, s.brake)
            shed = e.speed - s.speed_kmh
            if not e.counted and e.peak >= st.min_peak and shed >= st.min_speed_shed:
                e.counted = True
                self._add_onset(e.pos)
            if s.brake <= max(0.01, st.brake_threshold - _BRAKE_HYSTERESIS):
                self._braking, self._event = False, None

    def _add_onset(self: EngineState, pos: float) -> None:
        if not self._settings.learning_enabled:
            return
        sector = self._sector_of(pos)
        pos = round(pos, 5)
        if self._pass is not None and sector == self._sector:
            self._pass.onsets.append(pos)
        elif self._last_closed and self._last_closed[0] == sector and self._data:
            # confirmed just after the sector line: add to the run that was just saved
            self._last_closed[1].onsets.append(pos)
            self._rebuild_zones()
            self._save(self._data)

    def _lead_m(self: EngineState, speed_kmh: float) -> float:
        st = self._settings
        return max(_MIN_LEAD_M, max(speed_kmh / 3.6, 0.1) * st.warn_lead_s)

    def _emit_cues(self: EngineState, s: Sample, pos: float) -> None:
        st = self._settings
        lead = self._lead_m(s.speed_kmh)
        for z in self._zones:
            dist = ((z - pos) % 1.0) * self._length_m
            if dist > self._length_m / 2:
                dist -= self._length_m  # the point is behind us
            if abs(dist) <= st.brake_now_m and z not in self._fired_here:
                self._fired_here.add(z)
                if s.brake < st.skip_zone_if_braking:
                    self._on_cue(CueKind.HERE)
            elif st.brake_now_m < dist <= lead and z not in self._fired_warn:
                self._fired_warn.add(z)
                if s.brake < st.skip_zone_if_braking:
                    self._on_cue(CueKind.WARN)
