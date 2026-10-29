# Roadmap and pending work

Status after **0.6.0**: the quality/cleanup plan is complete. This page is the starting point for
the remaining product and engineering ideas. It is a working list, not a promise: pick one item,
make a branch and PR, and keep the gates green.

## How to pick up an item

1. Branch from `main` and keep one item per PR.
2. Follow the gates in [DEVELOPMENT.md](DEVELOPMENT.md): pre-commit, ruff, both `mypy` passes
   (`--platform win32` too), generated settings, tests with `-W error`, coverage floor.
3. Add a test for the behaviour you change. Offscreen UI tests use
   `pytest.mark.usefixtures("close_qt_windows")`.
4. Add a `CHANGELOG.md` line under `## Unreleased` and update the owning doc page.
5. Wait for CI. Download the PR's `windows-build` artifact and test in-game when the change is
   user-visible. Merge only after that.
6. Pre-1.0 policy: a settings or learned-data layout change may archive old files and start from
   defaults. **Never delete user data**; archive by move.

## Priority snapshot

| Item | Value | Risk | Effort |
|---|---|---|---|
| Race-cut pair | Done: guarded at read and in the engine | — | — |
| Global pause hotkey | Done: live, conflict-reporting global key | — | — |
| Windows adapter tests | Done: real paths run on the Windows CI leg | — | — |
| Settings key renames | Done: SETTINGS_VERSION 5, one-time settings reset | — | — |
| `mypy` for tests and scripts | Done: src, scripts and the test tree | — | — |
| `EngineState` protocol | Done: mixins checked against one protocol | — | — |
| Merge `PositionTimeline.at` with the crossing core | Code size | High | M |
| Centralise overlay colours | Done: one palette for the HUD | — | — |
| `acevo-sdk` 0.2 upgrade | Future game support | High (field) | M-L |
| Code signing | Trust / SmartScreen | External | — |
| Branch/archive cleanup | Done: `update-0.3.11` removed (content already on main) | — | — |

---

## 1. Race-cut pair: guarded (done)

The fallback is kept, but it now fails safe. The reader accepts only a plausible pair
(`1..60 000 ms` gained, `0..5 000 m` left to give back, a finite delta) and treats anything else as
no cut, so a shifted offset cannot drop sectors continuously. The engine applies the same bounds to
a `Sample` that did not come through the reader. Decoding also tolerates the SDK handing over the
raw block instead of hex text. The field notes and the valid-pair behaviour are unchanged; see
[GAME_DATA.md](GAME_DATA.md#track-limits) and the regression tests in
`tests/test_telemetry_audio.py` and `tests/test_track_limits.py`.

## 2. Global pause hotkey (done)

Settings -> App -> **Global pause hotkey** (default `Ctrl+Alt+P`, empty = off) pauses and resumes
learning from anywhere, including while driving. The parser accepts Ctrl/Alt/Shift/Win plus A-Z,
0-9 or F1-F12, rejects duplicate modifiers and unsupported keys with a sentence the form shows, and
requires a modifier for letters and digits so the app does not take that key from other windows.
`RegisterHotKey` is called directly through ctypes (no new dependency) and a Qt native event filter
handles `WM_HOTKEY`; the binding applies live, is re-registered when it changes, and is
unregistered on exit. A Windows conflict is reported in the tray and the log. The parser and
lifecycle are tested with a fake backend everywhere; the real API is exercised on the Windows CI
leg. See [GUIDE.md](GUIDE.md#pausing-learning) and [SETTINGS.md](SETTINGS.md).

## 3. Windows adapter tests (done)

The real process handle (`open_process_watcher`), the `winsound` backend and the single-instance
mutex now have tests marked `skipif(sys.platform != "win32")`. The Windows CI leg runs them, so a
broken ctypes call or a changed `winsound` API fails the build; Linux and macOS skip them cleanly,
and the existing fake-ctypes and injected-watcher tests still cover the surrounding logic
everywhere. See [DEVELOPMENT.md](DEVELOPMENT.md#where-the-tests-live).

## 4. Settings key renames (done)

`SETTINGS_VERSION` is now 5. The internal JSON keys are `brake_threshold`, `warn_lead_s`,
`brake_now_m`, `brake_now_hz`, `kept_runs`, `min_speed_shed` and `same_corner_m` (renamed from
`brake_on`, `lead_s`, `here_m`, `here_hz`, `top_runs`, `min_speed_drop` and `cluster_m`). The UI
labels did not change.

Under the settings policy there is no migration: a v4 file is moved to
`settings.version-4-<stamp>.json` and the app starts from defaults, so existing tuning is lost once.
The generated reference and every code and test reference use the new keys. `cluster_m` remains the
name of the engine's clustering distance parameter; only the stored setting was renamed.

## 5. `mypy` for tests and scripts (done)

`mypy` is strict for `src` and `scripts`; the whole `tests` tree is checked too, with the relaxed
test override: test functions may be untyped (one-off assertions), but their bodies and calls are
checked (`check_untyped_defs`). The shared harness (`conftest.py`, `engine_helpers.py`,
`gamelog_helpers.py`, `replay.py`) is kept fully annotated.

The scripts needed no code change (only `mypy_path = ["src"]` for the installed package). The test
tree exposed 128 errors, all type-only: missing annotations, narrowing `Optional` results, and
module-attribute lookups used to monkeypatch internals. They are fixed without changing what any
test asserts. The config guard test keeps the test tree and the override in place.

## 6. `EngineState` protocol (done)

The four mixins now annotate `self: EngineState`, a protocol in `engine/state.py` that declares the
shared attributes and cross-mixin operations. The 48 `# type: ignore[misc]` comments are gone, and
mypy checks every mixin access against the contract. `BrakeEngine` remains the implementation; the
mixins keep only the few attribute declarations whose assignments would otherwise infer a narrower
type. No runtime change.

## 7. Merge `PositionTimeline.at` with the crossing core (deferred)

**Current state:** `crossing` and `lap_start` now share `crossing_between`. `at` still has its own
interpolation because it carries different lap-number, jump/teleport and start/finish wrap rules.

**Why deferred:** it is the most delicate part of the timing code, and the current tests are the
only oracle for reset/teleport/wrap edge cases. The duplication is real but the risk/reward is poor
unless a concrete bug forces the change.

**If attempted:** extract a small segment helper that returns before/after, lap and share, keep the
rules explicit, and add cases for a reset inside a frame, a start/finish wrap, a future timestamp
and a missing earlier sample. **Branch:** `refactor/timeline-interpolation-core`.

## 8. Centralise overlay colours (done)

The overlay shadow, background, dim glyph, and the bar track, progress, outline and separator are
now RGBA constants in `theme` (values unchanged). The About tab formats its link colour from
`theme.ACCENT` instead of duplicating the hex string. A test pins the channel values so the
refactor cannot drift; a visual check at 1.00 and 1.50 is part of the PR review. `ui/icon.py` keeps
its own artwork palette on purpose: it is a generated image, not HUD chrome.

## 9. `acevo-sdk` 0.2 upgrade (future, field-tested)

**Current state:** pinned to `acevo-sdk>=0.1.1,<0.2.0`. The 0.2.0 release changes log parsing,
lap-authority and validity handling; the app's pin comment says 0.2.0 withholds frames until a clean
lap boundary and starves the live overlay. Dependabot is configured to ignore 0.2.x.

**To revisit:** remove the ignore, bump the pin, check `LapState.PUSH` → `LapState.VALID` usage,
verify live frames, sector lines, cuts and game-exit detection on track, then update the comment,
docs and ignore. This is a field-validation task, not a blind dependency bump.
**Branch:** `deps/acevo-sdk-0.2`.

## 10. Code signing (external)

The installer and exe are unsigned, so SmartScreen warns. Code signing needs a certificate or a
service such as SignPath (check eligibility against the non-commercial licence). If adopted, add the
signing step to `release.yml`, sign both the exe and the installer before checksums, and document
the certificate/secret rotation. No code change until the account and certificate exist.

## 11. Branch/archive cleanup (done)

`update-0.3.11` was the only local branch not merged into `main`. Its change is already on `main`
as `c27d847` (the same patch, cherry-picked); there was no remote branch and no need for an archive
tag, so the stale local branch was deleted. Nothing was lost.

---

## Non-goals for now

- A docs site/mkdocs, tox/nox, a devcontainer or pytest-xdist: the current uv + GitHub Actions setup
  is proportionate.
- QSettings for app settings: the versioned JSON is what makes the archive/reset policy explicit.
- A large engine rewrite: the learning behaviour is subtle and well tested; change it only with a
  regression test.
