"""Atomic JSON writes shared by settings and learned data."""

from __future__ import annotations

import contextlib
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def write_json_atomic(
    path: Path, payload: Mapping[str, Any], *, indent: int | None = None
) -> str | None:
    """Write ``payload`` through a temporary file, fsync and replace.

    Returns the error detail when the write failed; the previous file is left in place and the
    temporary file is removed. Returns ``None`` on success.
    """
    tmp = path.with_suffix(".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, indent=indent))
            handle.flush()
            os.fsync(handle.fileno())  # durable before the replace, not just in the cache
        os.replace(tmp, path)
    except OSError as exc:
        with contextlib.suppress(OSError):
            tmp.unlink()
        return str(exc)
    return None
