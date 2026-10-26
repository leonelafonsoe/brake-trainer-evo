"""The pure layers must not import Qt, adapters or the UI.

The boundaries are the reason most behaviour can be tested without a game, a display or Windows.
This makes the rule in AGENTS.md executable instead of aspirational.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "brake_trainer"

# Everything that must stay display-free. config and storage may assemble provenance metadata;
# the independent core may not reach for any adapter at all.
PURE_FILES = [
    SRC / "models.py",
    SRC / "outcomes.py",
    SRC / "config.py",
    SRC / "hotkey.py",
    SRC / "settings_spec.py",
    SRC / "timeline.py",
    SRC / "storage.py",
    *sorted((SRC / "engine").glob("*.py")),
]
CORE_FILES = [
    SRC / "models.py",
    SRC / "outcomes.py",
    SRC / "hotkey.py",
    SRC / "settings_spec.py",
    SRC / "timeline.py",
    *sorted((SRC / "engine").glob("*.py")),
]

FORBIDDEN_IN_PURE = frozenset(
    {"PySide6", "brake_trainer.app", "brake_trainer.controller", "brake_trainer.ui"}
)
FORBIDDEN_IN_CORE = FORBIDDEN_IN_PURE | frozenset(
    {
        "brake_trainer.telemetry",
        "brake_trainer.gamelog",
        "brake_trainer.audio",
        "brake_trainer.paths",
        "brake_trainer.buildinfo",
        "brake_trainer.logsetup",
        "brake_trainer.metadata",
    }
)


def _module_name(path: Path) -> str:
    """The dotted module name of a source file, as mypy and Python see it."""
    parts = list(path.relative_to(ROOT / "src").with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _resolve(path: Path, node: ast.ImportFrom) -> str | None:
    if node.level == 0:
        return node.module
    package = _module_name(path)
    if path.name != "__init__.py":
        package = package.rsplit(".", 1)[0]
    if node.level > 1:
        package = ".".join(package.split(".")[: -(node.level - 1)])
    return f"{package}.{node.module}" if node.module else package


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = _resolve(path, node)
            if module is not None:
                found.add(module)
    return found


def _violations(files: list[Path], forbidden: frozenset[str]) -> list[str]:
    found: list[str] = []
    for path in files:
        for module in sorted(_imports(path)):
            if any(module == name or module.startswith(f"{name}.") for name in forbidden):
                found.append(f"{path.relative_to(ROOT)} imports {module}")
    return found


def test_pure_modules_do_not_import_qt_or_the_ui():
    assert not _violations(PURE_FILES, FORBIDDEN_IN_PURE)


def test_the_independent_core_does_not_import_adapters():
    assert not _violations(CORE_FILES, FORBIDDEN_IN_CORE)
