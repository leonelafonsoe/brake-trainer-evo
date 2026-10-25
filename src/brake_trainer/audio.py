"""Cue sounds: short sine beeps generated in memory (no audio files needed)."""

from __future__ import annotations

import io
import logging
import math
import struct
import sys
import threading
import wave
from collections.abc import Callable

from .config import Settings
from .models import CueKind

log = logging.getLogger(__name__)

_RATE = 22050


def make_tone(freq_hz: int, duration_ms: int, volume: float) -> bytes:
    """A mono 16-bit WAV beep with short fades, so it doesn't click."""
    n = int(_RATE * duration_ms / 1000)
    fade = max(1, int(_RATE * 0.005))
    amp = 32767 * max(0.0, min(volume, 1.0)) * 0.8
    frames = bytearray()
    for i in range(n):
        env = min(1.0, i / fade, (n - 1 - i) / fade)
        frames += struct.pack("<h", int(amp * env * math.sin(2 * math.pi * freq_hz * i / _RATE)))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(_RATE)
        w.writeframes(bytes(frames))
    return buf.getvalue()


def _winsound_backend(wav: bytes) -> None:
    if sys.platform != "win32":
        return
    import winsound

    winsound.PlaySound(wav, winsound.SND_MEMORY)  # blocks for the length of the beep


_WARN_MS = 90  # tone lengths are fixed; the pitch and the volume are what a driver tunes
_HERE_MS = 120


class AudioPlayer:
    """Plays the warn / here cues. Each beep runs on its own short-lived thread."""

    def __init__(
        self,
        get_settings: Callable[[], Settings],
        backend: Callable[[bytes], None] | None = None,
    ) -> None:
        self._get_settings = get_settings
        self._backend = backend or (_winsound_backend if sys.platform == "win32" else None)
        self._cache: dict[tuple[int, int, float], bytes] = {}

    def _tone(self, kind: CueKind, st: Settings) -> bytes:
        hz, ms = (st.warn_hz, _WARN_MS) if kind is CueKind.WARN else (st.here_hz, _HERE_MS)
        key = (hz, ms, round(st.volume, 2))
        if key not in self._cache:
            self._cache[key] = make_tone(hz, ms, st.volume)
        return self._cache[key]

    def play(self, kind: CueKind, *, force: bool = False) -> None:
        """Play a cue. ``force`` ignores a zero volume (used by the test buttons)."""
        st = self._get_settings()
        if self._backend is None or (st.volume <= 0 and not force):
            return
        threading.Thread(target=self._run, args=(self._tone(kind, st),), daemon=True).start()

    def _run(self, wav: bytes) -> None:
        try:
            assert self._backend is not None
            self._backend(wav)
        except Exception:  # audio must never take the app down
            log.exception("Could not play cue")
