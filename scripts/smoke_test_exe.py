"""Start the packaged app, wait for its startup line, and stop it.

Windows CI runs this after the PyInstaller build. A package that cannot start (a missing Qt
plugin, a broken import, a bad frozen path) fails the job instead of being published, even though
the build itself succeeded. The app must also stay alive for a moment after its startup line: the
line is written before the event loop runs, so a crash on the first native event (a broken filter,
for example) would otherwise pass unnoticed.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path

STARTUP = "startup app="
GRACE_S = 2.0


def wait_for_startup(command: Sequence[str], timeout: float = 30.0, grace: float = GRACE_S) -> int:
    """Run ``command`` with a temporary app folder and wait for its startup log line.

    After the line is seen the process must still be running ``grace`` seconds later, so a crash
    in the first turn of the event loop fails the build. Raises :class:`SystemExit` with a useful
    message on a missing line, an early exit or a crash.
    """
    with tempfile.TemporaryDirectory(
        prefix="brake-trainer-smoke-", ignore_cleanup_errors=True
    ) as home:
        env = {**os.environ, "BRAKE_TRAINER_HOME": home}
        proc = subprocess.Popen(list(command), env=env)  # noqa: S603 - a path we built ourselves
        log = Path(home) / "brake_trainer.log"
        deadline = time.monotonic() + timeout
        try:
            while time.monotonic() < deadline:
                if log.is_file():
                    text = log.read_text(encoding="utf-8", errors="ignore")
                    if STARTUP in text:
                        print(text.splitlines()[0])
                        if grace > 0:
                            time.sleep(grace)
                            return_code = proc.poll()
                            if return_code is not None:
                                raise SystemExit(
                                    f"the packaged app exited with {return_code} just after its "
                                    "startup line"
                                )
                        return 0
                if proc.poll() is not None:
                    raise SystemExit(
                        f"the packaged app exited with {proc.returncode} before writing its "
                        "startup line"
                    )
                time.sleep(0.25)
            raise SystemExit(f"the packaged app did not write {STARTUP!r} within {timeout:g} s")
        finally:
            proc.terminate()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(5)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("exe", type=Path, help="path to the packaged executable")
    parser.add_argument("--timeout", type=float, default=30.0, help="seconds to wait")
    args = parser.parse_args()
    if not args.exe.is_file():
        raise SystemExit(f"missing executable: {args.exe}")
    return wait_for_startup([str(args.exe)], args.timeout)


if __name__ == "__main__":
    sys.exit(main())
