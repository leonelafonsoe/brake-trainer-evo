"""Logging setup: a rotating file next to the settings, plus the console.

The level is INFO by default. *Verbose* logging (the "Verbose (debug) logging" setting, the
``--debug`` command-line flag, or ``BRAKE_TRAINER_DEBUG=1``) lowers it to DEBUG and adds, in the
engine, a line for every change in the game's track-limit signals. That is what a report about a
missed sector needs: the live ``number_of_tyres_out`` and ``is_valid_lap`` values as they happen.

This module deliberately avoids importing the UI, so it can be used (and tested) on its own.
"""

from __future__ import annotations

import logging
import os
from contextlib import suppress
from logging.handlers import RotatingFileHandler

from .paths import log_path

APP_LOGGER = "brake_trainer"
DEBUG_ENV = "BRAKE_TRAINER_DEBUG"  # set to 1/true/on to force verbose logging at start-up

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_MAX_BYTES = 1_000_000
_BACKUPS = 3


def configure_logging(*, debug: bool = False) -> None:
    """Install the console and rotating-file handlers once, then set the level.

    Safe to call again (for example from a test): the handlers are only added the first time.
    """
    root = logging.getLogger()
    if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        fmt = logging.Formatter(_FORMAT)
        handlers: list[logging.Handler] = [logging.StreamHandler()]
        with suppress(OSError):  # a read-only or missing folder must not stop the app
            handlers.append(
                RotatingFileHandler(
                    log_path(), maxBytes=_MAX_BYTES, backupCount=_BACKUPS, encoding="utf-8"
                )
            )
        for handler in handlers:
            handler.setFormatter(fmt)
            root.addHandler(handler)
    set_debug(debug)


def set_debug(debug: bool) -> None:
    """Switch verbose logging on or off. Safe to call while the app is running."""
    logging.getLogger().setLevel(logging.DEBUG if debug else logging.INFO)


def is_debug() -> bool:
    return logging.getLogger().isEnabledFor(logging.DEBUG)


def debug_requested_on_startup(argv: list[str]) -> bool:
    """True if ``--debug`` is on the command line or ``BRAKE_TRAINER_DEBUG`` is set.

    ``--debug`` is also removed from ``argv`` so Qt never sees it.
    """
    flag = "--debug"
    forced = flag in argv
    if forced:
        argv.remove(flag)
    value = os.environ.get(DEBUG_ENV, "").strip().lower()
    return forced or value in {"1", "true", "yes", "on"}


def log_file() -> str:
    """The path of the log file, for messages and the "Open log folder" button."""
    return str(log_path())
