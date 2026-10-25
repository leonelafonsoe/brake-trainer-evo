from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from brake_trainer import __version__, buildinfo, logsetup
from brake_trainer.config import SETTINGS_VERSION
from brake_trainer.models import DATA_VERSION


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


def test_configure_logging_adds_its_handlers_only_once(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("BRAKE_TRAINER_HOME", str(tmp_path))
    monkeypatch.setenv(buildinfo.BUILD_ENV, "test-build")
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        with caplog.at_level(logging.INFO, logger=logsetup.APP_LOGGER):
            logsetup.configure_logging(debug=True)
            added = [h for h in root.handlers if h not in before]
            logsetup.configure_logging(debug=True)  # a second call must not duplicate them
        assert [h for h in root.handlers if h not in before] == added
        assert any(isinstance(h, RotatingFileHandler) for h in added)
        assert root.level == logging.DEBUG
        assert (tmp_path / "brake_trainer.log").exists()
        startup = [
            record.getMessage()
            for record in caplog.records
            if record.getMessage().startswith("startup ")
        ]
        assert len(startup) == 1  # once, not once per call
        line = startup[0]
        assert f"app={__version__}" in line
        assert "build=test-build" in line
        assert f"settings_version={SETTINGS_VERSION}" in line
        assert f"data_version={DATA_VERSION}" in line
        assert "debug=on" in line
        assert f"log={tmp_path / 'brake_trainer.log'}" in line
    finally:
        for handler in list(root.handlers):
            if handler not in before:
                root.removeHandler(handler)
                handler.close()
        root.setLevel(logging.INFO)
