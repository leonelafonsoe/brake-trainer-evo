"""Prepare a release: set the version everywhere and turn "Unreleased" into the new section.

    py scripts/bump_version.py 0.4.0

Then review the diff, commit it (usually through a pull request), and push the tag:

    git tag v0.4.0 && git push origin v0.4.0
"""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:-?(?:a|b|rc)\d+)?$")


def bump(root: Path, version: str, today: date) -> None:
    if not VERSION_RE.match(version):
        raise ValueError(f"'{version}' is not a version like 1.2.3 or 1.2.3-rc1")

    changelog_path = root / "CHANGELOG.md"
    changelog = changelog_path.read_text(encoding="utf-8")
    match = re.search(r"(?m)^## Unreleased[ \t]*\n(.*?)(?=^## |\Z)", changelog, re.S)
    if not match or not match.group(1).strip():
        raise ValueError("CHANGELOG.md needs a non-empty '## Unreleased' section to release")
    if re.search(rf"(?m)^## \[?{re.escape(version)}\]?(\s|$)", changelog):
        raise ValueError(f"CHANGELOG.md already has a section for {version}")
    body = match.group(1).strip("\n")
    section = f"## Unreleased\n\n## {version} - {today.isoformat()}\n\n{body}\n\n"
    changelog = changelog[: match.start()] + section + changelog[match.end() :]
    changelog_path.write_text(changelog, encoding="utf-8")

    for path, pattern, repl in (
        (root / "pyproject.toml", r'(?m)^version\s*=\s*"[^"]+"', f'version = "{version}"'),
        (
            root / "src" / "brake_trainer" / "__init__.py",
            r'__version__\s*=\s*"[^"]+"',
            f'__version__ = "{version}"',
        ),
    ):
        text = path.read_text(encoding="utf-8")
        new, count = re.subn(pattern, repl, text, count=1)
        if count != 1:
            raise ValueError(f"could not find the version in {path.name}")
        path.write_text(new, encoding="utf-8")

    if (root / "uv.lock").exists():
        # CI installs with --locked, so the lock's root version must move with pyproject.toml.
        subprocess.run(["uv", "lock"], cwd=root, check=True)


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    try:
        bump(ROOT, sys.argv[1], date.today())
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"version set to {sys.argv[1]}; review the diff, commit, then tag v{sys.argv[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
