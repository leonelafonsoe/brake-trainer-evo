"""The composition root's Windows-only decisions, tested without Windows."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from brake_trainer import app


def _fake_ctypes(last_error: int) -> SimpleNamespace:
    class Kernel32:
        def CreateMutexW(self, *args):
            return 123

        def GetLastError(self) -> int:
            return last_error

    return SimpleNamespace(windll=SimpleNamespace(kernel32=Kernel32()))


def test_the_single_instance_guard_never_blocks_off_windows(monkeypatch):
    monkeypatch.setattr(app.sys, "platform", "linux")
    assert app._create_app_mutex() is True


def test_the_single_instance_guard_allows_the_first_instance(monkeypatch):
    monkeypatch.setattr(app.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "ctypes", _fake_ctypes(0))
    assert app._create_app_mutex() is True


def test_the_single_instance_guard_refuses_a_second_instance(monkeypatch):
    monkeypatch.setattr(app.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "ctypes", _fake_ctypes(183))  # ERROR_ALREADY_EXISTS
    assert app._create_app_mutex() is False


@pytest.mark.skipif(sys.platform != "win32", reason="creates a real named Windows mutex")
def test_the_single_instance_mutex_allows_one_process_on_windows():
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handles: list[int | None] = []
    try:
        assert app._create_app_mutex() is True  # the first instance creates the mutex
        handles.append(app._app_mutex)
        assert app._create_app_mutex() is False  # the same name now already exists
        handles.append(app._app_mutex)
    finally:
        for handle in handles:
            if handle:
                kernel32.CloseHandle(handle)
        app._app_mutex = None
