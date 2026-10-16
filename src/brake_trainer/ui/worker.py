"""Background thread: telemetry -> engine -> cues, publishing view states to the UI."""

from __future__ import annotations

import asyncio
import logging
import time

from PySide6.QtCore import QThread, Signal

from ..audio import AudioPlayer
from ..config import Settings, SettingsHolder
from ..engine import BrakeEngine
from ..models import Sample, ViewState
from ..storage import DataEdit, TrackStore
from ..telemetry import TRACK_LIMITS_NOTE, ExitReason, TelemetryReader

log = logging.getLogger(__name__)

_EMIT_INTERVAL_S = 1 / 20  # UI refresh rate while samples stream in
_LIVE_TIMEOUT_S = 2.0  # no sample for this long = not live


class EngineWorker(QThread):
    state = Signal(object)  # ViewState
    message = Signal(str)
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
        self._engine.apply_settings(settings)

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
            self.message.emit("Telemetry worker crashed - see the log file")

    async def _main(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        log.warning(TRACK_LIMITS_NOTE)
        reader = TelemetryReader(
            lambda: self._holder.value,
            self._on_sample,
            self._log_message,
            self._on_game_state,
            on_restart=self._engine.reset_tracking,
        )
        ticker = asyncio.create_task(self._ticker())
        try:
            reason = await reader.run(self._stop)
        finally:
            ticker.cancel()
            self._engine.flush()
        if reason is ExitReason.GAME_CLOSED:
            self.game_closed.emit()

    def _log_message(self, text: str) -> None:
        log.info(text)
        self.message.emit(text)

    def _log_warning(self, text: str) -> None:
        log.warning(text)
        self.message.emit(text)

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
