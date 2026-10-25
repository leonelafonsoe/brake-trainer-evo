# AGENTS.md — working on Brake Trainer EVO

This file is the short map for contributors using an AI coding agent, and for the agents
themselves. It is not the manual: the detailed pages are linked.

## Read first

- [README.md](README.md) — what the app does and how to run it.
- [CONTRIBUTING.md](CONTRIBUTING.md) — contribution rules, fixtures, AI-assisted policy.
- [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) — full setup, checks and change recipes.
- [docs/DESIGN.md](docs/DESIGN.md) — architecture and the reasons behind it.
- [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md) — the behaviour the tests protect.
- [docs/DATA.md](docs/DATA.md) — storage formats, compatibility and failure policy.
- [docs/TELEMETRY.md](docs/TELEMETRY.md) — game data, the SDK and the game log.
- [tests/fixtures/README.md](tests/fixtures/README.md) — real-evidence fixture rules.

## Setup

Python **3.11+** is required. The app runs on Windows only, but the engine and almost all tests
run on Linux and macOS.

```powershell
# Windows
uv sync --extra dev
uv run pre-commit install
```

```bash
# Linux/macOS — the offscreen Qt platform is required by the UI tests
uv sync --extra dev
uv run pre-commit install
export QT_QPA_PLATFORM=offscreen
```

Run it from source with `uv run python -m brake_trainer` (or `uv run brake-trainer`).

## Gates

Run all of these before calling a change done. They are the same gates CI, Nightly and Release
use (`.github/actions/gates/action.yml`):

```bash
uv sync --frozen --extra dev
uv run pre-commit run --all-files
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest -q -W error
uv run pytest -q -W error --cov   # enforces the coverage floor
uv run python scripts/gen_settings_doc.py --check
uv run python scripts/release_notes.py --tag v0.5.0 --check
```

- A warning is an error (`filterwarnings = ["error"]`). Fix the warning; do not filter it away.
- Each test has a 60-second timeout, so a hang fails instead of blocking CI.
- Coverage has a floor in `pyproject.toml`. Raise it when coverage improves; never lower it to
  make a change pass.
- Do not reformat or rewrite unrelated files to make a check pass.

## Architecture boundaries

Keep these boundaries; they are what makes the app testable and the data safe.

- **Pure logic** — `models`, `config`, `engine`, `storage`, `timeline`. No Qt. `engine` takes its
  I/O through the injected `TrackStore`; never import the UI from here.
- **Adapters** — `telemetry`, `gamelog`, `audio`, `paths`, `buildinfo`. This is the only code that
  touches the SDK, the game's log, `tasklist`, `winsound`, the environment or the filesystem.
  Inject side effects so tests can run without a game or a display.
- **Provenance** — `metadata` and the build/version from `buildinfo` assemble what a saved file
  records.
- **UI** — `ui/*` and `app`. Thin. `ui/status.py` keeps the status-line decision as a pure
  function so it is testable without Qt.

More detail and the thread diagram: [docs/DESIGN.md](docs/DESIGN.md).

## Threading and lifecycle

- The worker thread (`ui/worker.py`) owns the engine. The UI thread must **never** call
  `BrakeEngine.update`, `apply_settings`, `apply_pending` or a store write directly.
- The UI sends immutable values: `EngineWorker.update_settings(Settings)`,
  `request_edit(DataEdit)` and `request_stop()`. They are queued and applied on the worker.
- The worker publishes immutable `ViewState` objects through Qt signals. Do not share mutable
  engine state with the UI.
- Shutdown must flush exactly once. `request_stop()` must work before the thread starts and while
  the loop is still probing. Do not add a second `flush()`.
- A failed save, delete or edit must stay visible; never report a false success.

## Data safety and compatibility

- **Never overwrite a learned-data or settings file this build could not read.** Unsafe files are
  moved to `data/quarantine/`; if the move fails, the path is blocked and saves are refused.
- Saves are atomic: write a temporary file, `fsync`, `os.replace`. On failure, keep the previous
  file and remove the temporary one.
- `DATA_VERSION` guards the learned-data layout. Bump it when a change to `TrackData.to_dict`
  would make an older build misread a file, and add a fixture plus a round-trip/migration test.
- `SETTINGS_VERSION` guards settings. Bump it when renaming or retiring keys; unknown keys from a
  newer file are preserved, while retired keys from older files are dropped.
- Archive by move, do not delete, when a file is unusable. Deleting learned data is a user action.

Formats and the full policy: [docs/DATA.md](docs/DATA.md).

## Change recipes

Use the detailed recipes in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md). In short:

- **New setting** — add a `SettingSpec` to `settings_spec.py`, add the matching typed field and
  default reference to `Settings`, regenerate `docs/SETTINGS.md`, and test the round-trip/clamping.
  If the engine uses it live, apply it in `apply_settings`.
- **Game-log parser** — start from a real, anonymized excerpt in `tests/fixtures/game_log/`; add
  the smallest test for `parse_line`/`line_time`; update `docs/TELEMETRY.md` if the format is
  explained there. Never invent a log format.
- **Learning or sectors** — use the synthetic `Driver` in `tests/conftest.py`; keep crossings
  interpolated between frames; test the boundary, teleport and deferred-line cases you touch.
  Update `docs/HOW_IT_WORKS.md`.
- **Storage schema** — bump the version, keep an old fixture loading, test round-trip and failure
  paths, and update `docs/DATA.md`.
- **UI** — add an offscreen test (module-level `pytest.mark.usefixtures("close_qt_windows")` for
  widgets); feed `ViewState` in, assert what is shown. Do not put learning logic in the UI.
- **Release** — follow [docs/RELEASING.md](docs/RELEASING.md). Bump once, add the changelog
  section, run the release check, then push the tag. The workflow is fail-closed.

## Fixtures

Real evidence beats an assumption. Add the smallest excerpt that proves one behaviour under
`tests/fixtures/`, remove names/IDs/paths, and note the game/app build in that folder's README.
Add a new fixture instead of silently replacing an old one. App logs are evidence, not test
input. Full rules: [CONTRIBUTING.md](CONTRIBUTING.md).

## Docs and generated files

- `docs/HOW_IT_WORKS.md` — behaviour.
- `docs/DESIGN.md` — why.
- `docs/TELEMETRY.md` — SDK and game log.
- `docs/TROUBLESHOOTING.md` — symptom and action.
- `docs/DATA.md` — file formats and compatibility.
- `docs/SETTINGS.md` is generated. **Never hand-edit it**; run
  `uv run python scripts/gen_settings_doc.py`.

Link instead of duplicating a long explanation, and keep each page owning one job.

## Release and versioning

- The version lives in `pyproject.toml` and `src/brake_trainer/__init__.py`; they must match.
- This branch targets **0.4.0**. Bump only as part of a release.
- A version tag must match the project version and have a non-empty changelog section; `## Unreleased`
  must be empty when tagging.
- Pre-release tags use the hyphen form (`v0.4.0-rc1`); the Release workflow treats only those as
  pre-releases.
- The release asserts the installer, zip and checksums, and stamps the commit into the build.

## Definition of done

A change is done when the gates pass, behaviour has a test, `CHANGELOG.md` has a line under
`## Unreleased`, and the affected docs are updated.

## Never do

- Never put Qt in the core modules or call the engine from the UI thread.
- Never overwrite a file the app could not read, or hide a failed write.
- Never invent game fields, log formats, measurements or test results.
- Never lower the coverage floor, silence a warning globally, or delete a test to make a change pass.
- Never commit a full game log, personal data, credentials or generated build output.
- Never do a large unreviewed refactor in a bug-fix change.
