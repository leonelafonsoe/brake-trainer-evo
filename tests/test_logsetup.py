from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from brake_trainer import logsetup


def test_set_debug_switches_the_root_level():
    root = logging.getLogger()
    try:
        logsetup.set_debug(True)
        assert root.level == logging.DEBUG
        assert logsetup.is_debug()
        logsetup.set_debug(False)
        assert root.level == logging.INFO
        assert not logsetup.is_debug()
    finally:
        root.setLevel(logging.INFO)


def test_debug_requested_on_startup_reads_the_flag_and_the_environment(monkeypatch):
    monkeypatch.delenv(logsetup.DEBUG_ENV, raising=False)
    argv = ["brake-trainer", "--debug"]
    assert logsetup.debug_requested_on_startup(argv) is True
    assert "--debug" not in argv  # removed so Qt never sees it
    assert logsetup.debug_requested_on_startup([]) is False

    monkeypatch.setenv(logsetup.DEBUG_ENV, "ON")
    assert logsetup.debug_requested_on_startup([]) is True
    monkeypatch.setenv(logsetup.DEBUG_ENV, "off")
    assert logsetup.debug_requested_on_startup([]) is False


def test_configure_logging_adds_its_handlers_only_once(monkeypatch, tmp_path):
    monkeypatch.setenv("BRAKE_TRAINER_HOME", str(tmp_path))
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        logsetup.configure_logging(debug=True)
        added = [h for h in root.handlers if h not in before]
        logsetup.configure_logging(debug=True)  # a second call must not duplicate them
        assert [h for h in root.handlers if h not in before] == added
        assert any(isinstance(h, RotatingFileHandler) for h in added)
        assert root.level == logging.DEBUG
        assert (tmp_path / "brake_trainer.log").exists()
    finally:
        for handler in list(root.handlers):
            if handler not in before:
                root.removeHandler(handler)
                handler.close()
        root.setLevel(logging.INFO)
