from __future__ import annotations

import importlib.util
import re
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
smoke = _load("smoke_test_exe")

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
    (tmp_path / "AGENTS.md").write_text("This branch targets **0.3.8**. Bump only for a release.\n")
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
    assert "--cov" in gates and "coverage.xml" in gates
    assert "gen_settings_doc.py --check" in gates

    for name in ("ci.yml", "nightly.yml", "release.yml"):
        workflow = (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
        assert "./.github/actions/gates" in workflow, name
        assert "timeout-minutes:" in workflow, name

    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "windows-latest" in ci and "matrix" in ci  # the tests run on Windows too
    assert "coverage-xml" in ci and "coverage.xml" in ci

    # The floor lives with the coverage config, so a local run and CI enforce the same number.
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "[tool.coverage.run]" in pyproject and "[tool.coverage.report]" in pyproject
    assert "fail_under = " in pyproject


def test_the_packaged_build_ships_the_licence_and_notices(tmp_path):
    build = _load("build_exe")
    source = tmp_path / "source"
    licenses = source / "packaging" / "licenses"
    licenses.mkdir(parents=True)
    for name in build.NOTICES:
        (source / name).write_text(name, encoding="utf-8")
    for name in ("MIT-acevo-sdk.txt", "LGPL-3.0.txt"):
        (licenses / name).write_text(name, encoding="utf-8")
    target = tmp_path / "dist" / "BrakeTrainerEvo"

    build.copy_notices(target, source)

    for name in build.NOTICES:
        assert (target / name).read_text(encoding="utf-8") == name
    for name in ("MIT-acevo-sdk.txt", "LGPL-3.0.txt"):
        assert (target / "licenses" / name).read_text(encoding="utf-8") == name

    # A missing licence must fail the build, not publish a package without one.
    with pytest.raises(FileNotFoundError):
        build.copy_notices(target, tmp_path / "empty")

    # The third-party texts are required too, even when the root notices are present.
    source_only_notices = tmp_path / "notices-only"
    source_only_notices.mkdir()
    for name in build.NOTICES:
        (source_only_notices / name).write_text(name, encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        build.copy_notices(target, source_only_notices)


def test_the_release_workflow_fails_closed_and_stamps_the_build():
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "BRAKE_TRAINER_BUILD: ${{ github.sha }}" in workflow
    # A uv-managed release must not fall back to the bare setup-python interpreter.
    assert 'uv run --locked --no-sync python -c "from brake_trainer import __version__' in workflow
    assert "SHA256SUMS.txt" in workflow
    assert "Checksum mismatch" in workflow
    assert "Missing release asset" in workflow
    assert "choco install innosetup --version=6.7.1" in workflow  # pinned, not latest
    # The old checksum step silently skipped whichever file was absent.
    assert "-ErrorAction SilentlyContinue |\n            ForEach-Object" not in workflow
    # The publish list is exact, not a glob that could match an old artifact.
    assert "dist/BrakeTrainerEvo-${{ steps.version.outputs.value }}-setup.exe" in workflow
    assert "dist/BrakeTrainerEvo-*-setup.exe" not in workflow

    build = (ROOT / "scripts" / "build_exe.py").read_text(encoding="utf-8")
    assert "BUILD_FILE" in build and "--add-data" in build  # the commit reaches the frozen app


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
    assert "This branch targets **0.3.9**" in (project / "AGENTS.md").read_text()
    assert notes.check_release("v0.3.9", project)[0] == "0.3.9"


def test_the_smoke_test_waits_for_the_startup_line(tmp_path):
    import sys

    command = [
        sys.executable,
        "-c",
        "import os, pathlib, time; "
        "pathlib.Path(os.environ['BRAKE_TRAINER_HOME'], 'brake_trainer.log')"
        ".write_text('startup app=0.0.0 build=test\\n'); time.sleep(5)",
    ]

    assert smoke.wait_for_startup(command, timeout=10, grace=0.1) == 0


def test_the_smoke_test_fails_when_the_app_crashes_after_its_startup_line():
    import sys

    command = [
        sys.executable,
        "-c",
        "import os, pathlib, time; "
        "pathlib.Path(os.environ['BRAKE_TRAINER_HOME'], 'brake_trainer.log')"
        ".write_text('startup app=0.0.0 build=test\\n'); time.sleep(0.2); raise SystemExit(7)",
    ]

    with pytest.raises(SystemExit, match="just after its startup line"):
        smoke.wait_for_startup(command, timeout=10, grace=1.0)


def test_the_smoke_test_fails_when_the_app_exits_early(tmp_path):
    import sys

    with pytest.raises(SystemExit, match="exited with 3"):
        smoke.wait_for_startup([sys.executable, "-c", "raise SystemExit(3)"], timeout=10)


def test_the_smoke_test_fails_without_a_startup_line(tmp_path):
    import sys

    with pytest.raises(SystemExit, match="did not write"):
        smoke.wait_for_startup([sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.5)


def test_bump_version_refreshes_the_lock_when_one_exists(project, monkeypatch):
    (project / "uv.lock").write_text("", encoding="utf-8")
    calls: list[list[str]] = []
    monkeypatch.setattr(bump.subprocess, "run", lambda args, **kwargs: calls.append(args))

    bump.bump(project, "0.3.9", date(2026, 10, 14))

    assert calls == [["uv", "lock"]]


def test_bump_version_refuses_bad_input(project):
    with pytest.raises(ValueError, match="not a version"):
        bump.bump(project, "v1", date.today())
    with pytest.raises(ValueError, match="already has"):
        bump.bump(project, "0.3.8", date.today())
    (project / "CHANGELOG.md").write_text("# Changelog\n\n## Unreleased\n\n## 0.3.8\n- x\n")
    with pytest.raises(ValueError, match="non-empty"):
        bump.bump(project, "0.4.0", date.today())


def test_third_party_actions_are_pinned_by_commit_sha():
    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        for line in path.read_text(encoding="utf-8").splitlines():
            uses = line.strip()
            if not uses.startswith("uses:") or "./.github" in uses:
                continue
            assert re.search(r"@[0-9a-f]{40}(\s|$)", uses), f"{path.name}: {uses}"


def test_dependabot_covers_uv_and_actions():
    config = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")

    # Dependabot only updates uv.lock for the uv ecosystem; "pip" would leave it stale.
    assert "package-ecosystem: uv" in config
    assert "package-ecosystem: github-actions" in config


def test_dependabot_ignores_the_incompatible_acevo_release():
    config = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")

    assert "dependency-name: acevo-sdk" in config
    assert 'versions: ["0.2.x"]' in config


def test_dependencies_are_locked_and_ci_refuses_a_stale_lock():
    assert (ROOT / "uv.lock").is_file()

    for name in ("ci.yml", "nightly.yml", "release.yml"):
        workflow = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        assert "astral-sh/setup-uv@" in workflow, name
        assert "uv sync --locked --extra dev" in workflow, name

    gates = (ROOT / ".github" / "actions" / "gates" / "action.yml").read_text(encoding="utf-8")
    assert "uv run --locked --no-sync" in gates


def test_the_installer_has_metadata_and_detects_a_running_app():
    installer = (ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8")
    app = (ROOT / "src" / "brake_trainer" / "app.py").read_text(encoding="utf-8")

    assert "AppMutex=BrakeTrainerEvo.App" in installer
    assert "AppPublisherURL=https://github.com/leonelafonsoe/brake-trainer-evo" in installer
    assert "AppSupportURL=" in installer and "AppUpdatesURL=" in installer
    assert "VersionInfoProductVersion={#AppVersion}" in installer
    assert "CloseApplications=yes" in installer
    # The mutex the installer checks must actually be created by the program.
    assert "CreateMutexW" in app and "BrakeTrainerEvo.App" in app


def test_the_gates_check_windows_types():
    gates = (ROOT / ".github" / "actions" / "gates" / "action.yml").read_text(encoding="utf-8")

    assert "mypy --platform win32" in gates


def test_mypy_checks_the_release_scripts_from_source():
    import tomllib

    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    mypy = config["tool"]["mypy"]

    assert {"src", "scripts"} <= set(mypy["files"])
    assert "src" in mypy["mypy_path"]


def test_every_windows_build_is_smoke_tested():
    for name in ("ci.yml", "nightly.yml", "release.yml"):
        workflow = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        assert "scripts/smoke_test_exe.py" in workflow, name


def test_nightly_and_release_audit_the_locked_dependencies():
    gates = (ROOT / ".github" / "actions" / "gates" / "action.yml").read_text(encoding="utf-8")
    assert "pip-audit" in gates
    assert "inputs.audit == 'true'" in gates

    for name in ("nightly.yml", "release.yml"):
        workflow = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        assert 'audit: "true"' in workflow, name


def test_the_security_workflow_audits_the_locked_dependencies():
    workflow = (ROOT / ".github" / "workflows" / "security.yml").read_text(encoding="utf-8")

    assert "schedule:" in workflow
    assert "uv export --locked --all-extras" in workflow
    assert "pip-audit" in workflow
    assert "uv sync --locked --extra dev" in workflow
    assert "astral-sh/setup-uv@" in workflow
