from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


notes = _load("release_notes")
bump = _load("bump_version")

CHANGELOG = """# Changelog

## Unreleased
- Something new.

## 0.3.8 - 2026-10-13
- Added a thing.
- Fixed another.

## [0.3.7]
- Old stuff.

## 0.4.0-rc1
- A candidate.
"""


@pytest.fixture
def project(tmp_path):
    (tmp_path / "src" / "brake_trainer").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0.3.8"\n')
    (tmp_path / "src" / "brake_trainer" / "__init__.py").write_text('__version__ = "0.3.8"\n')
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG)
    return tmp_path


def test_changelog_sections_are_found_with_and_without_dates_and_brackets():
    assert notes.changelog_section(CHANGELOG, "0.3.8") == "- Added a thing.\n- Fixed another."
    assert notes.changelog_section(CHANGELOG, "0.3.7") == "- Old stuff."
    assert notes.changelog_section(CHANGELOG, "Unreleased") == "- Something new."
    assert notes.changelog_section(CHANGELOG, "0.4.0rc1") == "- A candidate."  # rc1 == -rc1
    assert notes.changelog_section(CHANGELOG, "9.9.9") is None


def test_release_check_accepts_a_matching_tag(project):
    (project / "CHANGELOG.md").write_text(
        "# Changelog\n\n## Unreleased\n\n## 0.3.8 - 2026-10-13\n- Added a thing.\n"
    )
    version, text = notes.check_release("v0.3.8", project)
    assert version == "0.3.8" and "Added a thing" in text


def test_release_check_rejects_a_stale_released_section_while_unreleased_has_notes(project):
    # The fixture still has changes under Unreleased. Tagging the old 0.3.8 section would publish
    # notes that do not include them, so the check fails instead of shipping stale notes.
    with pytest.raises(ValueError, match="still has notes under '## Unreleased'"):
        notes.check_release("v0.3.8", project)


def test_the_project_version_and_the_tag_contract_agree():
    # pyproject.toml and __init__.py must agree, the result must be a tag the workflow accepts,
    # and that version must have a changelog section to publish.
    versions = notes.project_versions(ROOT)
    assert set(versions) == {"pyproject.toml", "__init__.py"}
    assert len(set(versions.values())) == 1, versions
    version = next(iter(versions.values()))
    match = notes.TAG_RE.match(f"v{version}")
    assert match is not None
    assert notes.normalize(match.group(1)) == notes.normalize(version)
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert notes.changelog_section(changelog, version)


@pytest.mark.parametrize(
    ("tag", "message"),
    [
        ("0.3.8", "not a release tag"),
        ("v0.3.9", "does not match"),
        ("vfoo", "not a release tag"),
    ],
)
def test_release_check_rejects_bad_tags(project, tag, message):
    with pytest.raises(ValueError, match=message):
        notes.check_release(tag, project)


def test_release_check_needs_changelog_notes(project):
    (project / "CHANGELOG.md").write_text("# Changelog\n\n## Unreleased\n- x\n")
    with pytest.raises(ValueError, match="no \\(or an empty\\)"):
        notes.check_release("v0.3.8", project)


def test_release_body_lists_downloads_and_can_leave_the_installer_out():
    body = notes.build_body("0.3.8", "- Added a thing.", "me/repo")
    assert body.startswith("- Added a thing.")
    assert "BrakeTrainerEvo-0.3.8-setup.exe" in body and "windows.zip" in body
    assert "SHA256SUMS.txt" in body and "SmartScreen" in body and "me/repo" in body
    assert "setup.exe" not in notes.build_body("0.3.8", "x", installer=False)


def test_nightly_body_mentions_commit_and_unreleased_changes():
    body = notes.build_nightly_body("- Something new.", "0123456789abcdef", "me/repo")
    assert "0123456" in body and "Something new" in body
    assert "No unreleased changes" in notes.build_nightly_body(None, "abc", "me/repo")


def test_every_workflow_that_tests_or_publishes_runs_the_shared_gates():
    # The nightly used to run a subset of the checks and the release duplicated them, so a change
    # could pass one path and fail another. Keep one definition of the gates.
    gates = (ROOT / ".github/actions/gates/action.yml").read_text(encoding="utf-8")
    assert "ruff format --check ." in gates
    assert "ruff check ." in gates
    assert "mypy" in gates
    assert "pytest -q -W error" in gates
    assert "gen_settings_doc.py --check" in gates

    for name in ("ci.yml", "nightly.yml", "release.yml"):
        workflow = (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
        assert "./.github/actions/gates" in workflow, name
        assert "timeout-minutes:" in workflow, name

    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "windows-latest" in ci and "matrix" in ci  # the tests run on Windows too


def test_bump_version_updates_everything_and_keeps_an_empty_unreleased(project):
    bump.bump(project, "0.3.9", date(2026, 10, 14))
    text = (project / "CHANGELOG.md").read_text()
    assert (
        text.index("## Unreleased") < text.index("## 0.3.9 - 2026-10-14") < text.index("## 0.3.8")
    )
    assert notes.changelog_section(text, "0.3.9") == "- Something new."
    assert notes.changelog_section(text, "Unreleased") == ""
    assert 'version = "0.3.9"' in (project / "pyproject.toml").read_text()
    assert '__version__ = "0.3.9"' in (project / "src/brake_trainer/__init__.py").read_text()
    assert notes.check_release("v0.3.9", project)[0] == "0.3.9"


def test_bump_version_refuses_bad_input(project):
    with pytest.raises(ValueError, match="not a version"):
        bump.bump(project, "v1", date.today())
    with pytest.raises(ValueError, match="already has"):
        bump.bump(project, "0.3.8", date.today())
    (project / "CHANGELOG.md").write_text("# Changelog\n\n## Unreleased\n\n## 0.3.8\n- x\n")
    with pytest.raises(ValueError, match="non-empty"):
        bump.bump(project, "0.4.0", date.today())
