"""Background thread: telemetry -> engine -> cues, publishing view states to the UI."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ..audio import AudioPlayer
from ..config import Settings, SettingsHolder
from ..engine import BrakeEngine
from ..gamelog import DEFAULT_LOG_DIR, GameLogTail
from ..models import Sample, ViewState
from ..storage import DataEdit, TrackStore
from ..telemetry import TRACK_LIMITS_NOTE, ExitReason, TelemetryReader

log = logging.getLogger(__name__)

_EMIT_INTERVAL_S = 1 / 20  # UI refresh rate while samples stream in
_LIVE_TIMEOUT_S = 2.0  # no sample for this long = not live


class EngineWorker(QThread):
    state = Signal(object)  # ViewState
    game_closed = Signal()
    data_changed = Signal()  # stored data was edited (refresh the data tab)

    def __init__(self, holder: SettingsHolder, store: TrackStore, audio: AudioPlayer) -> None:
        super().__init__()
        self._holder = holder
        self._audio = audio
        self._engine = BrakeEngine(
            holder.value,
            store,
            on_cue=audio.play,
            on_message=self._log_message,
            on_warning=self._log_warning,
            on_data_changed=self.data_changed.emit,
        )
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None
        self._game_running = False
        self._last_sample = 0.0
        self._last_emit = 0.0

    # ------------------------------------------------------------------ called from the UI thread

    def update_settings(self, settings: Settings) -> None:
        """Queue new settings; the worker applies them before the next sample or tick.

        The engine must only be mutated on its own thread: applying here would let a change land
        in the middle of ``update()``, between its reads of the old settings and its rebuild.
        """
        self._engine.queue_settings(settings)

    def request_edit(self, edit: DataEdit) -> None:
        """Delete stored data (applied on the worker thread, so it cannot be undone by a save)."""
        self._engine.queue_edit(edit)

    def request_stop(self) -> None:
        if self._loop is not None and self._stop is not None:
            self._loop.call_soon_threadsafe(self._stop.set)

    # ------------------------------------------------------------------ worker thread

    def run(self) -> None:
        try:
            asyncio.run(self._main())
        except Exception:
            log.exception("Telemetry worker crashed")

    async def _main(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        log.info(TRACK_LIMITS_NOTE)
        reader = TelemetryReader(
            lambda: self._holder.value,
            self._on_sample,
            self._log_message,
            self._on_game_state,
            on_restart=self._engine.reset_tracking,
        )
        ticker = asyncio.create_task(self._ticker())
        tail = self._start_log_tail()
        try:
            reason = await reader.run(self._stop)
        finally:
            ticker.cancel()
            if tail is not None:
                tail.cancel()
            self._engine.flush()
        if reason is ExitReason.GAME_CLOSED:
            self.game_closed.emit()

    def _start_log_tail(self) -> asyncio.Task[None] | None:
        """Follow the game's log for its cuts and its sector splits, if enabled."""
        settings = self._holder.value
        if not settings.use_game_log or self._stop is None:
            return None
        directory = (
            Path(settings.game_log_dir).expanduser() if settings.game_log_dir else DEFAULT_LOG_DIR
        )
        tail = GameLogTail(directory, self._on_cut, self._log_message, on_split=self._on_split)
        return asyncio.create_task(tail.run(self._stop))

    def _on_cut(self, reason: str, at: float) -> None:
        """A cut the game wrote to its log: the engine drops the sector it happened in.

        ``at`` is when the game wrote the line, which is when the cut was judged; the engine looks
        the car's position up from that time.
        """
        self._engine.report_infraction(reason, at)
        self._emit()

    def _on_split(self, index: int, at: float) -> None:
        """A sector split the game wrote to its log: the engine learns its line from it.

        ``at`` is when the car crossed that line, so the engine takes the position it had then.
        """
        self._engine.report_split(index, at)
        self._emit()

    def _log_message(self, text: str) -> None:
        log.info(text)

    def _log_warning(self, text: str) -> None:
        log.warning(text)

    def _on_game_state(self, running: bool) -> None:
        self._game_running = running
        self._emit()

    def _on_sample(self, sample: Sample) -> None:
        self._last_sample = time.monotonic()
        self._engine.update(sample)
        if self._last_sample - self._last_emit >= _EMIT_INTERVAL_S:
            self._emit()

    async def _ticker(self) -> None:
        while True:
            await asyncio.sleep(0.5)
            self._engine.apply_pending()  # edits requested while no samples arrive
            self._emit()

    def _emit(self) -> None:
        now = time.monotonic()
        self._last_emit = now
        live = now - self._last_sample < _LIVE_TIMEOUT_S
        self.state.emit(ViewState(self._engine.snapshot(), self._game_running, live))
