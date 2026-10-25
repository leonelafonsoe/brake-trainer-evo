from __future__ import annotations

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _generator():
    spec = importlib.util.spec_from_file_location(
        "gen_settings_doc", ROOT / "scripts" / "gen_settings_doc.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_settings_reference_is_up_to_date():
    expected = _generator().render()
    current = (ROOT / "docs" / "SETTINGS.md").read_text(encoding="utf-8")
    assert current == expected, "run: py scripts/gen_settings_doc.py"


def test_readme_lists_every_top_level_module():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    modules = {
        path.stem
        for path in (ROOT / "src" / "brake_trainer").glob("*.py")
        if path.stem not in {"__init__", "__main__"}
    }
    missing = sorted(name for name in modules if f"{name}.py" not in readme)
    assert not missing, f"README project layout is missing: {', '.join(missing)}"


def test_every_docs_page_is_linked_from_the_readme():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    missing = sorted(
        path.name for path in (ROOT / "docs").glob("*.md") if f"docs/{path.name}" not in readme
    )
    assert not missing, f"README does not link: {', '.join(missing)}"


def test_the_agents_target_version_matches_the_package():
    from brake_trainer import __version__

    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    match = re.search(r"This branch targets \*\*(\d+\.\d+\.\d+)\*\*", text)
    assert match is not None, "AGENTS.md lost its 'This branch targets **X.Y.Z**' line"
    assert match.group(1) == __version__


def test_data_doc_matches_the_log_rotation():
    from brake_trainer import logsetup

    doc = (ROOT / "docs" / "DATA.md").read_text(encoding="utf-8")
    size_mb = logsetup._MAX_BYTES // 1_000_000
    assert f"about {size_mb} MB x {logsetup._BACKUPS}" in doc
