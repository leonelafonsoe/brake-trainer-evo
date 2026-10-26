"""The global pause hotkey: parsing and the register/unregister lifecycle.

The Win32 backend and the Qt message filter are exercised by the synthetic-message test here and,
for the real API, on the Windows CI leg. Everything else runs without Windows or a display.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes

import pytest

from brake_trainer.hotkey import (
    HOTKEY_ID,
    MOD_ALT,
    MOD_CONTROL,
    MOD_SHIFT,
    MOD_WIN,
    Hotkey,
    HotkeyControl,
    HotkeyError,
    parse_hotkey,
)
from brake_trainer.ui.hotkey import ERROR_HOTKEY_ALREADY_REGISTERED, WindowsHotkey

pytestmark = pytest.mark.usefixtures("qapp")


@pytest.mark.parametrize(
    ("text", "modifiers", "vk", "canonical"),
    [
        ("Ctrl+Alt+P", MOD_CONTROL | MOD_ALT, ord("P"), "Ctrl+Alt+P"),
        ("ctrl + alt + p", MOD_CONTROL | MOD_ALT, ord("P"), "Ctrl+Alt+P"),
        ("Alt+Ctrl+P", MOD_CONTROL | MOD_ALT, ord("P"), "Ctrl+Alt+P"),
        ("Alt+Control+Shift+F12", MOD_CONTROL | MOD_ALT | MOD_SHIFT, 0x7B, "Ctrl+Alt+Shift+F12"),
        ("win+9", MOD_WIN, ord("9"), "Win+9"),
        ("Control+0", MOD_CONTROL, ord("0"), "Ctrl+0"),
        ("Shift+F1", MOD_SHIFT, 0x70, "Shift+F1"),
        ("F9", 0, 0x78, "F9"),  # a function key may be used alone
        ("  Ctrl+Alt+P  ", MOD_CONTROL | MOD_ALT, ord("P"), "Ctrl+Alt+P"),
    ],
)
def test_a_valid_hotkey_is_normalised(text, modifiers, vk, canonical):
    hotkey = parse_hotkey(text)

    assert hotkey == Hotkey(modifiers=modifiers, vk=vk, text=canonical)


@pytest.mark.parametrize("text", ["", "   ", "\t"])
def test_an_empty_setting_turns_the_hotkey_off(text):
    assert parse_hotkey(text) is None


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("P", "Use a modifier"),
        ("1", "Use a modifier"),
        ("Ctrl", "Add a key"),
        ("Ctrl+Alt", "Add a key"),
        ("Ctrl+Ctrl+P", "used twice"),
        ("Ctrl+Control+P", "used twice"),  # the two spellings are the same modifier
        ("Ctrl+Alt+F13", "not a supported key"),
        ("Ctrl+Alt+Space", "not a supported key"),
        ("Ctrl++P", "is not a valid hotkey"),
        ("Ctrl+Alt+P+Q", "Use one key"),
        ("Ctrl+Alt+Mouse1", "not a supported key"),
    ],
)
def test_an_invalid_hotkey_says_what_is_wrong(text, message):
    with pytest.raises(HotkeyError, match=message):
        parse_hotkey(text)


class FakeBackend:
    def __init__(self, problem: str = "") -> None:
        self.registered: list[Hotkey] = []
        self.unregistered = 0
        self.closed = 0
        self.problem = problem

    def register(self, hotkey: Hotkey) -> str:
        self.registered.append(hotkey)
        return self.problem

    def unregister(self) -> None:
        self.unregistered += 1

    def close(self) -> None:
        self.closed += 1


def test_a_binding_is_registered_once_and_a_new_setting_replaces_it():
    backend = FakeBackend()
    control = HotkeyControl(backend)

    assert control.apply("Ctrl+Alt+P")
    assert [hotkey.text for hotkey in backend.registered] == ["Ctrl+Alt+P"]

    # Every settings change reapplies the value, including a pause toggle: no second registration.
    assert control.apply("Ctrl+Alt+P")
    assert len(backend.registered) == 1
    assert backend.unregistered == 0

    assert control.apply("Shift+F9")
    assert [hotkey.text for hotkey in backend.registered] == ["Ctrl+Alt+P", "Shift+F9"]
    assert backend.unregistered == 1


def test_an_empty_setting_unregisters_and_turns_the_hotkey_off():
    backend = FakeBackend()
    control = HotkeyControl(backend)
    control.apply("Ctrl+Alt+P")

    assert not control.apply("")
    assert backend.unregistered == 1

    assert not control.apply("")  # still off: no second unregister
    assert backend.unregistered == 1


def test_a_conflict_is_reported_once_and_is_not_retried_on_every_settings_change():
    backend = FakeBackend("Ctrl+Alt+P is already used by another application.")
    problems: list[str] = []
    control = HotkeyControl(backend, problems.append)

    assert not control.apply("Ctrl+Alt+P")
    assert problems == ["Ctrl+Alt+P is already used by another application."]

    assert not control.apply("Ctrl+Alt+P")  # the same failing value: no repeated tray message
    assert len(problems) == 1

    backend.problem = ""
    assert control.apply("Ctrl+Alt+O")  # a new value retries
    assert len(problems) == 1


def test_an_invalid_setting_is_reported_but_the_old_key_is_released():
    backend = FakeBackend()
    problems: list[str] = []
    control = HotkeyControl(backend, problems.append)
    control.apply("Ctrl+Alt+P")

    assert not control.apply("P")

    assert backend.registered == [Hotkey(MOD_CONTROL | MOD_ALT, ord("P"), "Ctrl+Alt+P")]
    assert backend.unregistered == 1
    assert problems and "Use a modifier" in problems[0]


def test_without_a_platform_backend_the_hotkey_is_unsupported_without_raising(caplog):
    problems: list[str] = []
    control = HotkeyControl(None, problems.append)

    with caplog.at_level(logging.INFO, logger="brake_trainer.hotkey"):
        assert not control.apply("Ctrl+Alt+P")

    assert problems == []  # nothing the driver can act on for a platform the app does not ship on
    assert "not available" in caplog.text


def test_close_unregisters_and_releases_the_backend_once():
    backend = FakeBackend()
    control = HotkeyControl(backend)
    control.apply("Ctrl+Alt+P")

    control.close()
    control.close()

    assert backend.unregistered == 1
    assert backend.closed == 1


def test_a_wm_hotkey_message_for_our_id_calls_the_pause_callback():
    from brake_trainer.hotkey import WM_HOTKEY

    pressed: list[int] = []
    hotkey = WindowsHotkey(lambda: pressed.append(1), install_filter=False)
    message = wintypes.MSG()
    message.message = WM_HOTKEY
    message.wParam = HOTKEY_ID

    assert hotkey.nativeEventFilter(b"windows_dispatcher_MSG", ctypes.addressof(message)) is True
    assert pressed == [1]

    message.wParam = HOTKEY_ID + 1  # another program's hotkey message
    assert hotkey.nativeEventFilter(b"windows_dispatcher_MSG", ctypes.addressof(message)) is False
    assert pressed == [1]

    message.wParam = HOTKEY_ID
    message.message = 0x0400  # not WM_HOTKEY
    assert hotkey.nativeEventFilter(b"windows_dispatcher_MSG", ctypes.addressof(message)) is False
    assert pressed == [1]

    hotkey.close()


class FakeUser32:
    def __init__(self, accepted: bool = True) -> None:
        self.accepted = accepted
        self.calls: list[tuple[object, ...]] = []

    def RegisterHotKey(self, hwnd, hotkey_id, modifiers, vk) -> bool:
        self.calls.append(("register", hwnd, hotkey_id, modifiers, vk))
        return self.accepted

    def UnregisterHotKey(self, hwnd, hotkey_id) -> bool:
        self.calls.append(("unregister", hwnd, hotkey_id))
        return True


def test_the_win32_backend_registers_and_unregisters_the_parsed_binding():
    user32 = FakeUser32()
    hotkey = WindowsHotkey(lambda: None, user32=user32, install_filter=False)
    binding = parse_hotkey("Ctrl+Alt+P")
    assert binding is not None

    assert hotkey.register(binding) == ""
    hotkey.unregister()
    hotkey.unregister()  # already released: no second system call

    assert user32.calls == [
        ("register", None, HOTKEY_ID, MOD_CONTROL | MOD_ALT, ord("P")),
        ("unregister", None, HOTKEY_ID),
    ]


def test_the_win32_backend_reports_a_taken_combination_and_a_generic_refusal(monkeypatch):
    binding = parse_hotkey("Ctrl+Alt+P")
    assert binding is not None
    user32 = FakeUser32(accepted=False)
    hotkey = WindowsHotkey(lambda: None, user32=user32, install_filter=False)

    monkeypatch.setattr(
        ctypes, "get_last_error", lambda: ERROR_HOTKEY_ALREADY_REGISTERED, raising=False
    )
    assert "already used" in hotkey.register(binding)

    monkeypatch.setattr(ctypes, "get_last_error", lambda: 5, raising=False)  # access denied
    assert "Windows refused" in hotkey.register(binding)


def test_the_hotkey_is_unsupported_off_windows(monkeypatch):
    from brake_trainer.ui import hotkey as ui_hotkey

    monkeypatch.setattr(ui_hotkey.sys, "platform", "linux")
    control = ui_hotkey.create_pause_hotkey(lambda: None, lambda _message: None)

    assert not control.apply("Ctrl+Alt+P")
    control.close()


@pytest.mark.skipif(sys.platform != "win32", reason="uses the real RegisterHotKey API")
def test_the_win32_backend_registers_and_reports_a_taken_combination():
    binding = parse_hotkey("Ctrl+Alt+Shift+F12")
    assert binding is not None
    first = WindowsHotkey(lambda: None, hotkey_id=0x4A01, install_filter=False)
    second = WindowsHotkey(lambda: None, hotkey_id=0x4A02, install_filter=False)
    try:
        assert first.register(binding) == ""
        assert "already used" in second.register(binding)
    finally:
        first.close()
        second.close()
