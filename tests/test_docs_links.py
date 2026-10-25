"""Every relative Markdown link and anchor in the repository resolves."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", ".venv", "build", "dist", "node_modules"}
FENCE = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)
INLINE_CODE = re.compile(r"`[^`]*`")
HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
REFERENCE = re.compile(r"^\[[^\]]+\]:\s*(\S+)", re.MULTILINE)
EXPLICIT_ANCHOR = re.compile(r"<a\s+(?:name|id)=\"([^\"]+)\"", re.IGNORECASE)


def _markdown_files() -> list[Path]:
    files = []
    for path in sorted(ROOT.rglob("*.md")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if any(part.startswith(".") and part != ".github" for part in path.relative_to(ROOT).parts):
            continue
        files.append(path)
    return files


def _visible_text(path: Path) -> str:
    """The file without fenced code blocks or inline code spans."""
    text = path.read_text(encoding="utf-8")
    return INLINE_CODE.sub("", FENCE.sub("", text))


def _slug(text: str) -> str:
    """Approximate GitHub's heading anchor slug."""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = text.replace("`", "").replace("*", "")
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    return text.replace(" ", "-")


def _anchors(path: Path) -> set[str]:
    anchors = set(EXPLICIT_ANCHOR.findall(path.read_text(encoding="utf-8")))
    seen: dict[str, int] = {}
    for line in _visible_text(path).splitlines():
        match = HEADING.match(line)
        if not match:
            continue
        base = _slug(match.group(2))
        count = seen.get(base, 0)
        anchors.add(base if count == 0 else f"{base}-{count}")
        seen[base] = count + 1
    return anchors


def _targets(path: Path) -> list[str]:
    text = _visible_text(path)
    return [*LINK.findall(text), *REFERENCE.findall(text)]


def test_every_relative_markdown_link_resolves():
    checked = 0
    failures: list[str] = []
    for source in _markdown_files():
        for raw in _targets(source):
            target = unquote(raw)
            parts = urlsplit(target)
            if parts.scheme:
                continue
            file_part, _, anchor = target.partition("#")
            file_part = file_part.split("?", 1)[0]
            destination = source if not file_part else (source.parent / file_part).resolve()
            if not destination.exists():
                failures.append(f"{source.relative_to(ROOT)}: missing {target}")
                continue
            if anchor and destination.suffix == ".md" and anchor not in _anchors(destination):
                failures.append(f"{source.relative_to(ROOT)}: missing anchor {target}")
                continue
            checked += 1
    assert not failures, "Broken Markdown links:\n" + "\n".join(failures)
    assert checked > 20, "the link scanner found too few links to be meaningful"


def test_the_link_scanner_finds_the_expected_files():
    files = _markdown_files()
    names = {path.relative_to(ROOT).as_posix() for path in files}

    assert "README.md" in names
    assert "docs/DEVELOPMENT.md" in names
    assert any(name.startswith(".github/") for name in names)
    assert len(files) >= 12
