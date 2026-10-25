"""Release notes from CHANGELOG.md, and version checks for the release workflows.

    py scripts/release_notes.py --tag v0.3.8 --check            # validate tag, version, changelog
    py scripts/release_notes.py --tag v0.3.8 --out notes.md     # write the GitHub release body
    py scripts/release_notes.py --unreleased --sha abc123 --out notes.md   # nightly build body

CHANGELOG.md headings look like ``## 0.3.8`` or ``## 0.3.8 - 2026-10-13``. ``## Unreleased``
collects changes that are not released yet.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TAG_RE = re.compile(r"^v(\d+\.\d+\.\d+(?:-?(?:a|b|rc)\d+)?)$")


def normalize(version: str) -> str:
    """0.4.0-rc1 and 0.4.0rc1 are the same release."""
    return version.lstrip("v").replace("-", "")


def changelog_section(changelog: str, name: str) -> str | None:
    """The text under ``## <name>`` (up to the next ``## ``), or None if there is no heading."""
    lines = changelog.splitlines()
    wanted = normalize(name).lower()
    for i, line in enumerate(lines):
        match = re.match(r"^##\s+\[?([^\]\s]+)\]?(?:\s+-\s+.*)?\s*$", line)
        if match and normalize(match.group(1)).lower() == wanted:
            body: list[str] = []
            for nxt in lines[i + 1 :]:
                if nxt.startswith("## "):
                    break
                body.append(nxt)
            return "\n".join(body).strip()
    return None


def project_versions(root: Path = ROOT) -> dict[str, str]:
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    init = (root / "src" / "brake_trainer" / "__init__.py").read_text(encoding="utf-8")
    found = {
        "pyproject.toml": re.search(r'(?m)^version\s*=\s*"([^"]+)"', pyproject),
        "__init__.py": re.search(r'__version__\s*=\s*"([^"]+)"', init),
    }
    return {name: m.group(1) for name, m in found.items() if m}


def check_release(tag: str, root: Path = ROOT) -> tuple[str, str]:
    """Validate a release tag against the project files; returns (version, notes)."""
    match = TAG_RE.match(tag)
    if not match:
        raise ValueError(f"'{tag}' is not a release tag like v1.2.3 or v1.2.3-rc1")
    version = match.group(1)
    for name, value in project_versions(root).items():
        if normalize(value) != normalize(version):
            raise ValueError(f"tag {tag} does not match the version in {name} ({value})")
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    notes = changelog_section(changelog, version)
    if not notes:
        raise ValueError(f"CHANGELOG.md has no (or an empty) '## {version}' section")
    if changelog_section(changelog, "Unreleased"):
        # A non-empty Unreleased next to an existing version section means the notes for this tag
        # are stale: the changes that were not bumped yet are missing from the release body.
        raise ValueError(
            f"CHANGELOG.md still has notes under '## Unreleased'; "
            f"run scripts/bump_version.py {version} before tagging {tag}"
        )
    return version, notes


_DOWNLOADS = """### Download

| File | What it is |
| --- | --- |
{rows}

The programs are **not code-signed**, so Windows SmartScreen may warn you the first time. See
[Troubleshooting](https://github.com/{repo}/blob/main/docs/GUIDE.md#installing-and-running).
Verify a download against `SHA256SUMS.txt` if you like.

> This project is largely AI-written ("vibe coded") and only play-tested by its maintainer. Expect
> rough edges and please [report bugs](https://github.com/{repo}/issues).
"""


def build_body(version: str, notes: str, repo: str = "OWNER/REPO", installer: bool = True) -> str:
    rows = []
    if installer:
        installer_row = (
            f"| `BrakeTrainerEvo-{version}-setup.exe` | Installer (no admin rights needed) |"
        )
        rows.append(installer_row)
    zip_row = (
        f"| `BrakeTrainerEvo-{version}-windows.zip` | Portable: unzip, run `BrakeTrainerEvo.exe` |"
    )
    rows.append(zip_row)
    rows.append("| `SHA256SUMS.txt` | Checksums of the files above |")
    downloads = _DOWNLOADS.format(rows="\n".join(rows), repo=repo)
    return f"{notes}\n\n---\n\n{downloads}"


def build_nightly_body(unreleased: str | None, sha: str, repo: str = "OWNER/REPO") -> str:
    short = sha[:7] or "unknown"
    changes = unreleased or "_No unreleased changes are listed in the changelog yet._"
    return (
        f"Automatic build of the latest `main` ({short}). It may be unstable; "
        "use the latest versioned release for something steady.\n\n"
        f"## Changes since the last release\n\n{changes}\n\n---\n\n"
        f"Download the `BrakeTrainerEvo-nightly-windows.zip` asset, unzip it and run "
        f"`BrakeTrainerEvo.exe`. See [Troubleshooting](https://github.com/{repo}/blob/main/"
        "docs/GUIDE.md#installing-and-running) if Windows warns about it.\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--tag", help="release tag, for example v0.3.8")
    parser.add_argument("--unreleased", action="store_true", help="notes for a nightly build")
    parser.add_argument("--check", action="store_true", help="only validate, write nothing")
    parser.add_argument("--no-installer", action="store_true", help="leave the installer out")
    parser.add_argument("--sha", default="", help="commit for the nightly body")
    parser.add_argument("--repo", default="OWNER/REPO", help="owner/name, for links")
    parser.add_argument("--out", type=Path, help="write the body here")
    args = parser.parse_args(argv)

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    try:
        if args.unreleased:
            body = build_nightly_body(
                changelog_section(changelog, "Unreleased"), args.sha, args.repo
            )
        elif args.tag:
            version, notes = check_release(args.tag)
            body = build_body(version, notes, args.repo, installer=not args.no_installer)
        else:
            parser.error("give --tag or --unreleased")
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.check:
        print(f"ok: {args.tag} matches the project version and has release notes")
    elif args.out:
        args.out.write_text(body, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
