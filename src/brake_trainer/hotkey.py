"""The global pause hotkey: parse a binding and keep one registration in sync.

The Win32 call and the Qt message filter live in :mod:`brake_trainer.ui.hotkey`. This module stays
pure so the parser and the register/unregister lifecycle are tested without Windows or a display.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

log = logging.getLogger(__name__)

# Win32 modifier flags and the message WM_HOTKEY. Kept here because the parser and the UI adapter
# share them; ``RegisterHotKey`` expects exactly these bits.
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
WM_HOTKEY = 0x0312

# One fixed id: the app owns a single global pause key, so a message with any other id is foreign.
HOTKEY_ID = 1

DEFAULT_PAUSE_HOTKEY = "Ctrl+Alt+P"

_MODIFIERS = {
    "CTRL": MOD_CONTROL,
    "CONTROL": MOD_CONTROL,
    "ALT": MOD_ALT,
    "SHIFT": MOD_SHIFT,
    "WIN": MOD_WIN,
    "WINDOWS": MOD_WIN,
}
_MODIFIER_ORDER = (
    (MOD_CONTROL, "Ctrl"),
    (MOD_ALT, "Alt"),
    (MOD_SHIFT, "Shift"),
    (MOD_WIN, "Win"),
)
_KEYS = {
    **{chr(code): code for code in range(ord("A"), ord("Z") + 1)},
    **{str(digit): ord(str(digit)) for digit in range(10)},
    # Virtual-key codes: F1 is 0x70, F12 is 0x7B.
    **{f"F{number}": 0x6F + number for number in range(1, 13)},
}


class HotkeyError(ValueError):
    """The text is not a hotkey this app can register."""


@dataclass(frozen=True, slots=True)
class Hotkey:
    """One parsed binding, in the form Windows and the settings text both use."""

    modifiers: int
    vk: int
    text: str  # canonical, e.g. "Ctrl+Alt+P"


def parse_hotkey(text: str) -> Hotkey | None:
    """Parse the ``pause_hotkey`` setting; ``None`` means off (empty or whitespace).

    A letter or digit needs at least one modifier, because a bare key would be taken from every
    other application, including the game and any chat window. Function keys may be used alone:
    they do not type text and are a common choice for a cockpit switch.

    Raises :class:`HotkeyError` with a sentence the settings window can show as-is.
    """
    raw = text.strip()
    if not raw:
        return None
    tokens = [token.strip() for token in raw.split("+")]
    if any(not token for token in tokens):
        raise HotkeyError(f"'{raw}' is not a valid hotkey. Use for example Ctrl+Alt+P.")

    modifiers = 0
    keys: list[str] = []
    for token in tokens:
        modifier = _MODIFIERS.get(token.upper())
        if modifier is None:
            keys.append(token.upper())
            continue
        if modifiers & modifier:
            name = next(name for bit, name in _MODIFIER_ORDER if bit == modifier)
            raise HotkeyError(f"{name} is used twice.")
        modifiers |= modifier

    if not keys:
        raise HotkeyError("Add a key to the hotkey, for example Ctrl+Alt+P.")
    if len(keys) > 1:
        raise HotkeyError("Use one key, for example Ctrl+Alt+P.")
    key = keys[0]
    vk = _KEYS.get(key)
    if vk is None:
        raise HotkeyError(f"'{key}' is not a supported key. Use A-Z, 0-9 or F1-F12.")
    if not modifiers and not key.startswith("F"):
        raise HotkeyError(
            f"Use a modifier (Ctrl, Alt, Shift or Win) with {key}, or a function key such as F9."
        )

    names = [name for bit, name in _MODIFIER_ORDER if modifiers & bit]
    return Hotkey(modifiers=modifiers, vk=vk, text="+".join([*names, key]))


class HotkeyBackend(Protocol):
    """The platform part: register one binding, drop it, and release the message hook."""

    def register(self, hotkey: Hotkey) -> str:
        """Register ``hotkey``; return "" on success or a sentence saying why Windows refused."""
        ...

    def unregister(self) -> None: ...

    def close(self) -> None: ...


class HotkeyControl:
    """Keep the one global pause hotkey in sync with the setting.

    ``apply`` is called for every settings change, including a pause toggle, so it must be
    idempotent: re-registering an unchanged binding would drop a key press and repeat a conflict
    message. A value that failed is remembered too; a new value (or the next app start) retries.
    """

    def __init__(
        self,
        backend: HotkeyBackend | None,
        on_problem: Callable[[str], None] = lambda message: None,
    ) -> None:
        self._backend = backend
        self._on_problem = on_problem
        self._applied: str | None = None
        self._active = False

    def apply(self, text: str) -> bool:
        """Make the hotkey match ``text``; True when it is registered now."""
        wanted = text.strip()
        if wanted == self._applied:
            return self._active
        self._applied = wanted
        self._release()
        if not wanted:
            log.info("Global pause hotkey is off")
            return False
        if self._backend is None:
            log.info("Global pause hotkey is not available on this platform")
            return False
        try:
            hotkey = parse_hotkey(wanted)
        except HotkeyError as exc:
            self._problem(str(exc))
            return False
        assert hotkey is not None  # empty text was handled above
        problem = self._backend.register(hotkey)
        if problem:
            self._problem(problem)
            return False
        self._active = True
        log.info("Global pause hotkey registered: %s", hotkey.text)
        return True

    def close(self) -> None:
        """Unregister the key and release the platform hook; safe to call more than once."""
        self._release()
        if self._backend is not None:
            self._backend.close()
            self._backend = None
        self._applied = None

    def _release(self) -> None:
        if self._active and self._backend is not None:
            self._backend.unregister()
        self._active = False

    def _problem(self, message: str) -> None:
        log.warning("Global pause hotkey: %s", message)
        self._on_problem(message)
