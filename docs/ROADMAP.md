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
| Global pause hotkey | Driver UX | Medium-high | M |
| Windows adapter tests | Done: real paths run on the Windows CI leg | — | — |
| Settings key renames | Cosmetic / internal | Medium (settings reset) | M |
| `mypy` for tests and scripts | Type safety | Low | M-L |
| `EngineState` protocol | Type debt | Low runtime, high churn | M-L |
| Merge `PositionTimeline.at` with the crossing core | Code size | High | M |
| Centralise overlay colours | Consistency | Low | S |
| `acevo-sdk` 0.2 upgrade | Future game support | High (field) | M-L |
| Code signing | Trust / SmartScreen | External | — |

---

## 1. Race-cut pair: guarded (done)

The fallback is kept, but it now fails safe. The reader accepts only a plausible pair
(`1..60 000 ms` gained, `0..5 000 m` left to give back, a finite delta) and treats anything else as
no cut, so a shifted offset cannot drop sectors continuously. The engine applies the same bounds to
a `Sample` that did not come through the reader. Decoding also tolerates the SDK handing over the
raw block instead of hex text. The field notes and the valid-pair behaviour are unchanged; see
[GAME_DATA.md](GAME_DATA.md#track-limits) and the regression tests in
`tests/test_telemetry_audio.py` and `tests/test_track_limits.py`.

## 2. Global pause hotkey

**Where:** new `src/brake_trainer/ui/hotkey.py` (or a Win32 adapter), `app.py`, settings metadata.

**Current state:** pause/resume is available from the overlay button, tray menu and Settings. The
overlay is a non-focusable tool window, so there is no keyboard path while driving.

**Proposal:**

- Add a setting `pause_hotkey` (text, default `Ctrl+Alt+P`, empty = off) and validate it at apply
  time. Parse modifiers (Ctrl/Alt/Shift/Win) plus a key (A-Z, 0-9, F1-F12); reject duplicate
  modifiers and unsupported keys with a clear message.
- Implement registration through Win32 `RegisterHotKey` on a message-only window or a Qt
  `QAbstractNativeEventFilter` receiving `WM_HOTKEY`.
- Register on startup and on setting change; unregister on quit and on failure. A conflict
  (`ERROR_HOTKEY_ALREADY_REGISTERED`) must be visible (tray message + log), not silent.
- Keep the setting live only where possible; otherwise say "applies on restart" next to it, as the
  telemetry rate does.
- No new dependency. Inject the Win32 backend so the parser and lifecycle are testable on Linux.

**Tests:** parser accepts/rejects; fake backend gets one register/unregister per change; a conflict
does not crash the app; non-Windows returns "unsupported" without raising.

**Docs:** GUIDE controls and SETTINGS (generated). **Branch:** `feat/global-pause-hotkey`.

## 3. Windows adapter tests (done)

The real process handle (`open_process_watcher`), the `winsound` backend and the single-instance
mutex now have tests marked `skipif(sys.platform != "win32")`. The Windows CI leg runs them, so a
broken ctypes call or a changed `winsound` API fails the build; Linux and macOS skip them cleanly,
and the existing fake-ctypes and injected-watcher tests still cover the surrounding logic
everywhere. See [DEVELOPMENT.md](DEVELOPMENT.md#where-the-tests-live).

## 4. Settings key renames (optional, product decision)

**Current JSON keys:** `brake_on`, `lead_s`, `here_m`, `here_hz`, `top_runs`, `min_speed_drop`,
`cluster_m`. The UI labels are already clear; the JSON keys are internal.

**Proposed names:** `brake_threshold`, `warn_lead_s`, `brake_now_m`, `brake_now_hz`, `kept_runs`,
`min_speed_shed`, `same_corner_m`.

**Impact:** a rename requires `SETTINGS_VERSION` 5. Under the 0.6.0 policy, an existing settings
file is archived and the app starts from defaults, so users lose their tuning once. Labels and
generated docs must be checked; all engine references and tests need the new field names.

**Recommendation:** only do this if the reset is acceptable and the names will stay. It is cosmetic
for users and moderately broad in code. **Branch:** `refactor/settings-key-renames`.

## 5. `mypy` for tests and scripts (optional)

**Current state:** `mypy` is strict for `src` only. Running it over `tests` + `scripts` currently
reports **613 errors in 35 files**, mostly missing annotations in tests. Test code is not
production code, but helper drift (fixtures, replay harness, release scripts) is real.

**Proposal (choose one):**

- **Relaxed test typing:** add `tests` and `scripts` to `files`, then a per-module override for
  `tests` and the top-level script modules that disables `disallow_untyped_defs` /
  `disallow_untyped_calls` while keeping `check_untyped_defs` on. Fix the remaining real errors.
- **Scripts first:** include only `scripts` in strict mypy; leave tests out.
- **Do nothing:** keep the strict source pass. This is a deliberate choice, not an oversight.

**Acceptance:** both `mypy` and `mypy --platform win32` pass with the chosen scope; no runtime change.

## 6. `EngineState` protocol (deferred)

**Current state:** the engine is split across four mixins. Their methods annotate
`self: BrakeEngine`, and mypy's explicit-self rule forces **48** `# type: ignore[misc]` (11 in
`passes.py`, 18 in `lines.py`, 15 in `limits.py`, 4 in `cues.py`).

**Why it was deferred:** a checked protocol would declare the shared state and every cross-mixin
method — roughly 100 lines duplicating signatures — for no runtime behaviour. The ignores are
localized and the engine has strong behaviour tests.

**If attempted:** add `engine/state.py` with an `EngineState` `Protocol` (attributes and methods),
annotate each mixin's `self` with it, and let mypy prove the contract. Do it in one mechanical PR
with no behaviour change. **Branch:** `refactor/engine-state-protocol`.

## 7. Merge `PositionTimeline.at` with the crossing core (deferred)

**Current state:** `crossing` and `lap_start` now share `crossing_between`. `at` still has its own
interpolation because it carries different lap-number, jump/teleport and start/finish wrap rules.

**Why deferred:** it is the most delicate part of the timing code, and the current tests are the
only oracle for reset/teleport/wrap edge cases. The duplication is real but the risk/reward is poor
unless a concrete bug forces the change.

**If attempted:** extract a small segment helper that returns before/after, lap and share, keep the
rules explicit, and add cases for a reset inside a frame, a start/finish wrap, a future timestamp
and a missing earlier sample. **Branch:** `refactor/timeline-interpolation-core`.

## 8. Centralise overlay colours and metrics (low priority)

**Current state:** most metrics are now scaled through `_px`, but some colours are still literal:
the shadow (`QColor(0, 0, 0, 230)`), the default overlay background (`QColor(12, 14, 18)`) and the
bar colours in `ui/widgets.py`. The About link duplicates `theme.ACCENT`.

**Proposal:** add `theme.OVERLAY_BG`, `SHADOW`, bar track/fill/separator constants and use them in
`overlay.py`/`widgets.py`/`about_page.py`. Keep the existing values byte-for-byte so the look does
not change. **Acceptance:** visual check at 1.00 and 1.50; no test can pin colours cheaply.
**Branch:** `refactor/overlay-theme-constants`.

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

## 11. Branch/archive cleanup

`update-0.3.11` is the only local branch not merged into `main`; its change was cherry-picked into
the 0.3.11 history. Inspect `b265935`, tag it under `archive/` if it matters, then delete it. All
other merged branches and stale `/tmp` worktrees were cleaned up after 0.6.0.

---

## Non-goals for now

- A docs site/mkdocs, tox/nox, a devcontainer or pytest-xdist: the current uv + GitHub Actions setup
  is proportionate.
- QSettings for app settings: the versioned JSON is what makes the archive/reset policy explicit.
- A large engine rewrite: the learning behaviour is subtle and well tested; change it only with a
  regression test.
