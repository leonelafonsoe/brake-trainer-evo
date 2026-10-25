"""Background thread: telemetry -> engine -> cues, publishing view states to the UI."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
import time
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ..audio import AudioPlayer
from ..config import Settings, SettingsHolder
from ..engine import BrakeEngine
from ..gamelog import GameLogSupervisor
from ..logsetup import log_file
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
        # Set from any thread, including before the thread has started and before the loop exists.
        self._stop_requested = threading.Event()
        self._error = ""  # a telemetry failure the overlay should show
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
        """Ask the worker to stop. Safe from any thread and before the thread has started.

        The asyncio event may not exist yet (the thread was never started, or ``_main`` is still
        setting up), so the request is also kept in a plain event that ``_main`` checks before it
        waits for telemetry.
        """
        self._stop_requested.set()
        loop, stop = self._loop, self._stop
        if loop is not None and stop is not None:
            with contextlib.suppress(RuntimeError):  # the loop has already closed
                loop.call_soon_threadsafe(stop.set)

    # ------------------------------------------------------------------ worker thread

    def run(self) -> None:
        try:
            asyncio.run(self._main())
        except Exception:
            log.exception("Telemetry worker crashed")
        finally:
            self._loop = None
            self._stop = None
            self._engine.flush()  # exactly once, including when the loop failed to start

    async def _main(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stop = asyncio.Event()
        if self._stop_requested.is_set():
            self._stop.set()  # stop was requested before the loop existed
        log.info(TRACK_LIMITS_NOTE)
        reader = TelemetryReader(
            lambda: self._holder.value,
            self._on_sample,
            self._log_message,
            self._on_game_state,
            on_error=self._on_telemetry_error,
            on_restart=self._engine.reset_tracking,
        )
        ticker = asyncio.create_task(self._ticker())
        logs = asyncio.create_task(
            GameLogSupervisor(
                lambda: self._holder.value,
                self._on_cut,
                self._log_message,
                on_split=self._on_split,
            ).run(self._stop)
        )
        try:
            reason = await reader.run(self._stop)
        finally:
            ticker.cancel()
            logs.cancel()
            # Await both: a cancelled task's exception is otherwise only reported when the loop
            # closes, and the game-log tail must be finished before the engine is flushed.
            for result in await asyncio.gather(ticker, logs, return_exceptions=True):
                if isinstance(result, Exception):
                    log.error("Worker task failed", exc_info=result)
        if reason is ExitReason.GAME_CLOSED:
            self.game_closed.emit()

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

    def _on_telemetry_error(self, detail: str) -> None:
        """A retryable capture/read failure, or "" once the reader has recovered.

        The detail goes to the log with the exception; the status line gets the short reason and
        the log file name, so a driver can find the full message without a long path on the HUD.
        """
        text = f"Telemetry failed: {detail} · see {Path(log_file()).name}" if detail else ""
        if text == self._error:
            return
        self._error = text
        if text:
            log.error("%s (log: %s)", text, log_file())
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
        self.state.emit(ViewState(self._engine.snapshot(), self._game_running, live, self._error))
