"""Build the Windows executable with PyInstaller.

Usage (from the project root, in the virtual environment):
    py scripts/build_exe.py            # folder build  -> dist/BrakeTrainerEvo/ + a versioned zip
    py scripts/build_exe.py --onefile  # single .exe (slower start, more antivirus false alarms)

The icon comes from packaging/icon.ico (regenerate it with scripts/make_icon.py).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from brake_trainer import __version__  # noqa: E402

NAME = "BrakeTrainerEvo"
DEFAULT_ICON = ROOT / "packaging" / "icon.ico"


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

    print("Running:", " ".join(cmd))
    result = subprocess.run(cmd, cwd=ROOT, check=False)
    if result.returncode:
        return result.returncode

    if args.onefile:
        print(f"\nDone: {ROOT / 'dist' / (NAME + '.exe')}")
    else:
        base = ROOT / "dist" / f"{NAME}-{__version__}-windows"
        archive = shutil.make_archive(str(base), "zip", ROOT / "dist", NAME)
        print(f"\nDone: {ROOT / 'dist' / NAME}  (zipped: {archive})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
