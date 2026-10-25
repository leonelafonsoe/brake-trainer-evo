"""Build the Windows executable with PyInstaller.

Usage (from the project root, in the virtual environment):
    py scripts/build_exe.py            # folder build  -> dist/BrakeTrainerEvo/ + a versioned zip
    py scripts/build_exe.py --onefile  # single .exe (slower start, more antivirus false alarms)

The icon comes from packaging/icon.ico (regenerate it with scripts/make_icon.py).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from brake_trainer import __version__  # noqa: E402
from brake_trainer.buildinfo import BUILD_FILE, build_id  # noqa: E402

NAME = "BrakeTrainerEvo"
DEFAULT_ICON = ROOT / "packaging" / "icon.ico"
NOTICES = ("LICENSE", "THIRD_PARTY_NOTICES.md")


def copy_notices(target: Path, root: Path = ROOT) -> None:
    """Put the licence and third-party notices beside the program.

    They travel with the portable zip and, because the installer copies this folder, with an
    installed copy too. A missing file fails the build rather than shipping without it.
    """
    target.mkdir(parents=True, exist_ok=True)
    for name in NOTICES:
        source = root / name
        if not source.is_file():
            raise FileNotFoundError(f"missing distribution file: {source}")
        shutil.copy2(source, target / name)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--onefile", action="store_true", help="build a single .exe")
    parser.add_argument("--icon", type=Path, default=DEFAULT_ICON, help="the .ico to use")
    args = parser.parse_args()

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name",
        NAME,
        "--paths",
        str(ROOT / "src"),
        "--collect-submodules",
        "acevo",
        "--distpath",
        str(ROOT / "dist"),
        "--workpath",
        str(ROOT / "build"),
        "--specpath",
        str(ROOT / "build"),
        "--onefile" if args.onefile else "--onedir",
    ]
    if args.icon.exists():
        print(f"Using icon: {args.icon}")
        cmd += ["--icon", str(args.icon)]
    else:
        print(f"(no icon found at {args.icon}; building without one)")
    cmd.append(str(ROOT / "packaging" / "entry.py"))

    # A frozen app cannot ask git which commit it came from, so bake the identifier in as data
    # next to the program. CI sets BRAKE_TRAINER_BUILD to the commit; a local build falls back to
    # the checkout's git description.
    build = build_id()
    print(f"Build: {build}")
    with tempfile.TemporaryDirectory(prefix="brake-trainer-build-") as meta:
        build_file = Path(meta) / BUILD_FILE
        build_file.write_text(f"{build}\n", encoding="utf-8")
        cmd += ["--add-data", f"{build_file}{os.pathsep}."]
        print("Running:", " ".join(cmd))
        result = subprocess.run(cmd, cwd=ROOT, check=False)
    if result.returncode:
        return result.returncode

    target = ROOT / "dist" if args.onefile else ROOT / "dist" / NAME
    try:
        copy_notices(target)
    except OSError as exc:
        print(f"Could not copy the licence and notices: {exc}", file=sys.stderr)
        return 1

    if args.onefile:
        print(f"\nDone: {ROOT / 'dist' / (NAME + '.exe')}")
    else:
        base = ROOT / "dist" / f"{NAME}-{__version__}-windows"
        archive = shutil.make_archive(str(base), "zip", ROOT / "dist", NAME)
        print(f"\nDone: {ROOT / 'dist' / NAME}  (zipped: {archive})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
