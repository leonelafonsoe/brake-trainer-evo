"""The Windows side of the global pause hotkey: ``RegisterHotKey`` and a ``WM_HOTKEY`` filter."""

from __future__ import annotations

import ctypes
import logging
import sys
from collections.abc import Callable
from ctypes import wintypes
from typing import Any, cast

from PySide6.QtCore import QAbstractNativeEventFilter, QByteArray, QCoreApplication

from ..hotkey import HOTKEY_ID, WM_HOTKEY, Hotkey, HotkeyControl

log = logging.getLogger(__name__)

# ctypes only defines these on Windows, and both mypy passes (Linux and Windows) check this file.
_WIN32 = cast(Any, ctypes)

ERROR_HOTKEY_ALREADY_REGISTERED = 1409
_WINDOWS_EVENTS = (b"windows_generic_MSG", b"windows_dispatcher_MSG")


class WindowsHotkey(QAbstractNativeEventFilter):
    """Register one hotkey with Windows and report ``WM_HOTKEY`` to ``on_pressed``.

    ``RegisterHotKey`` is given the thread's message queue (``hwnd`` is NULL), and Qt's event
    dispatcher already pumps that queue, so a native event filter is enough: no message-only
    window and no extra thread. The filter is installed on the application, so create this after
    the ``QApplication`` exists.
    """

    def __init__(
        self,
        on_pressed: Callable[[], None],
        *,
        user32: Any | None = None,
        hotkey_id: int = HOTKEY_ID,
        install_filter: bool = True,
    ) -> None:
        super().__init__()
        self._on_pressed = on_pressed
        self._user32 = user32
        self._id = hotkey_id
        self._registered = False
        self._installed = False
        self._message_error_logged = False
        if install_filter:
            application = QCoreApplication.instance()
            if application is None:
                raise RuntimeError("The global hotkey needs the QApplication to exist first")
            application.installNativeEventFilter(self)
            self._installed = True

    def register(self, hotkey: Hotkey) -> str:
        """Register ``hotkey``; return "" on success or a sentence explaining the refusal."""
        if self._user32 is None:
            self._user32 = _user32()
        if not self._user32.RegisterHotKey(None, self._id, hotkey.modifiers, hotkey.vk):
            error = _WIN32.get_last_error()
            if error == ERROR_HOTKEY_ALREADY_REGISTERED:
                return f"{hotkey.text} is already used by another application."
            return f"Windows refused {hotkey.text} (error {error})."
        self._registered = True
        return ""

    def unregister(self) -> None:
        if self._registered and self._user32 is not None:
            self._user32.UnregisterHotKey(None, self._id)
            self._registered = False

    def close(self) -> None:
        self.unregister()
        if self._installed:
            application = QCoreApplication.instance()
            if application is not None:
                application.removeNativeEventFilter(self)
            self._installed = False

    def nativeEventFilter(
        self,
        event_type: QByteArray | bytes | bytearray | memoryview,
        # The stub says int, but PySide hands over the MSG pointer as a shiboken VoidPtr.
        message: Any,
    ) -> bool:
        try:
            name = event_type.data() if isinstance(event_type, QByteArray) else event_type
            if bytes(name) not in _WINDOWS_EVENTS:
                return False
            msg = wintypes.MSG.from_address(int(message))
            if msg.message != WM_HOTKEY or msg.wParam != self._id:
                return False
        except Exception:
            # This runs for every Windows message: an escape here takes the event loop (and the
            # app) down, so a message we cannot read is ignored, loudly but only once.
            if not self._message_error_logged:
                self._message_error_logged = True
                log.exception("Could not read a native Windows message")
            return False
        try:
            self._on_pressed()
        except Exception:
            log.exception("The pause hotkey action failed")
        return True


def _user32() -> Any:
    """user32 with the signatures and last-error handling ``RegisterHotKey`` needs."""
    user32 = _WIN32.WinDLL("user32", use_last_error=True)
    user32.RegisterHotKey.argtypes = [
        wintypes.HWND,
        ctypes.c_int,
        wintypes.UINT,
        wintypes.UINT,
    ]
    user32.RegisterHotKey.restype = wintypes.BOOL
    user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.UnregisterHotKey.restype = wintypes.BOOL
    return user32


def create_pause_hotkey(
    on_pressed: Callable[[], None],
    on_problem: Callable[[str], None],
) -> HotkeyControl:
    """The pause hotkey for this platform; elsewhere a control that reports it unsupported."""
    if sys.platform != "win32":
        return HotkeyControl(None, on_problem)
    return HotkeyControl(WindowsHotkey(on_pressed), on_problem)
