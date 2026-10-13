# Contributing

Bug reports, ideas and pull requests are welcome.

## Set up

```powershell
git clone <your fork>
cd brake-trainer-evo
py -m venv .venv
.venv\Scripts\Activate.ps1          # or call .venv\Scripts\python.exe directly
pip install -e ".[dev]"
```

You do not need Windows or the game to run the tests: the engine is pure Python and the
telemetry layer is tested with fakes. On Linux/macOS set `QT_QPA_PLATFORM=offscreen` if a test
touches Qt.

## Before opening a pull request

```powershell
ruff format .
ruff check .
mypy
pytest
```

- Keep the engine (`engine.py`, `storage.py`, `models.py`, `config.py`) free of Qt imports.
- Add or update tests for behaviour changes. `tests/conftest.py` has a synthetic `Driver` that
  drives an engine around a fake track, which makes most scenarios a few lines.
- If you add a setting, add it to `Settings`, to the `TABS` table in `ui/settings_window.py`, and
  regenerate the reference: `py scripts/gen_settings_doc.py`.
- Update `CHANGELOG.md` and, if behaviour changes, `docs/HOW_IT_WORKS.md`.
- Small, focused pull requests are easier to review than large ones.

## What happens to your pull request

1. **Checks** run on every pull request: lint, format, types and tests.
2. **A Windows build** is made too. Open the run on the pull request's *Checks* tab and download the
   `BrakeTrainerEvo-windows-...` artifact to try your change (or let a reviewer try it).
3. After it is merged into `main`, the **Nightly** pre-release on the Releases page is refreshed with
   a build of the newest code.
4. Maintainers publish numbered versions: see [docs/RELEASING.md](docs/RELEASING.md).

Add a line about your change under `## Unreleased` in `CHANGELOG.md`; it becomes the release notes.

## AI-assisted contributions

This project is itself largely written with AI, so AI-assisted pull requests are welcome. The rule
is simple: **a human must be accountable for every change.**

- **Read it.** You should understand every line you submit and be able to explain it in review.
- **Run it.** Run the checks above. For anything that touches telemetry, audio or the UI, try it
  with the game and say so in the pull request.
- **Say so.** Tick the "AI-assisted" box in the pull request template and name the tool. It is not
  a mark against you; it helps reviewers know where to look harder.
- **Describe it yourself.** Write the pull request description in your own words, including what you
  tested.
- **Keep it focused.** Small, reviewable changes. Large, unreviewed or machine-generated bulk changes
  (mass refactors, rewritten docs, dependency churn) may be closed without a detailed review.
- **No invented facts.** Do not submit made-up game details, telemetry fields or measurements.
  If you are not sure something is true, say so in the pull request.

The same applies to issues: AI-written bug reports are fine if you checked that the problem is real.

## Reporting a bug

Please include the app version, what you were doing (track, car, session type), what you
expected, and the relevant lines of `%APPDATA%\BrakeTrainerEvo\brake_trainer.log`.

## License of contributions

The project is licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE). By submitting
a contribution you agree that it is provided under that same license.
