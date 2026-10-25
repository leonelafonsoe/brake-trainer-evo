"""The composition root's Windows-only decisions, tested without Windows."""

from __future__ import annotations

import sys
from types import SimpleNamespace

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
