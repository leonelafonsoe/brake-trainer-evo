# Changelog

All notable changes to this project. Versions before 0.3 were a single-file script.

## Unreleased

### Changed

- Settings no longer carry `settings_version` as a field and there is no migration code. A settings
  file from another version (older, newer, or pre-versioning) is moved to
  `settings.version-<n>-<stamp>.json` and the app starts from defaults, so no build rewrites a layout
  it does not understand. `SETTINGS_VERSION` remains the schema number written into the file.
- CI installs the lock with `uv sync --locked`, so a stale `uv.lock` fails instead of being silently
  ignored. Dependabot now tracks the `uv` ecosystem, pre-commit hooks run in CI, and Nightly and
  Release enforce the coverage floor.
- The settings-application and shutdown policy moved out of `app.py` into a Qt-free `AppController`,
  so the save-failure warning, tray sync, dialog reload and worker shutdown are tested directly. The
  worker's game-log callbacks and idle tick now have integration tests too.
- A legacy learned-data filename is resolved once per identity instead of being re-read on every
  sector save.
- The UI now uses a dark Fusion palette with visible focus and disabled states, so native controls
  match the rest of the window. Apply is the default dialog button (Enter no longer risks Reset),
  the overlay buttons have accessible names, and the default overlay position follows the screen
  under the cursor.
- An architecture test enforces that the pure layers never import Qt, the UI or the adapters, and
  real fixture bytes are marked binary in Git so a Windows checkout cannot rewrite them.
- Nightly and Release run `pip-audit` against the locked dependencies, and the weekly Security
  workflow is back on the same `setup-python` release as the other workflows.
- The Data tab now renders an immutable snapshot published by the worker. The UI never reads or
  quarantines the learned-data folder itself, so a scan can no longer stall the overlay or race a
  save.
- The HUD distance row keeps one height when it switches between a phase word and a number. Deleting
  a whole sector now asks for confirmation, like deleting an entry does.
- If the monitor holding the HUD is unplugged or disabled, the overlay moves back to the default
  position instead of staying off-screen.
- Every pull request now type-checks with `mypy --platform win32` as well as the host platform, so
  Windows-only `ctypes`/`winsound` mistakes fail in CI instead of only in Nightly. This caught the
  `Any` return in `_create_app_mutex`.
- Game-process detection moved out of `TelemetryReader.run` into a small `_GameWatch`, with unit
  tests for the handle, two-miss fallback and probing cadence. The reader loop is correspondingly
  smaller.
- `report_split` now has separate audit and learning paths, so the verbose line-comparison code is
  no longer entangled with the fresh-entry learning rules. Behaviour is unchanged.
- A settings-save failure is shown as a tray notification when the tray supports messages, instead
  of a modal dialog that could take keyboard focus from the game. It still falls back to the dialog
  when the tray is unavailable or hidden.
- The history line crossings and the live sector transition now share the same interpolation helper;
  the timing arithmetic is identical and the tests pin the same results.
- Settings and learned data now share one atomic JSON writer (temporary file, `fsync`, `replace`,
  cleanup on failure), so the two cannot drift in how they protect a failed write.
- Settings type validation now lives in `SettingSpec.coerce`: one rule for every field, including
  rejecting booleans as numbers and non-finite floats, instead of a kind ladder in the loader.
- Learned data is validated on load: runs are sorted fastest-first, and a non-positive time, a
  non-finite value or an onset outside 0..1 quarantines the file instead of using it.
- Documentation is six pages instead of ten: `GUIDE.md` (behaviour and troubleshooting),
  `GAME_DATA.md` (telemetry, log, files and compatibility), `DESIGN.md`, `DEVELOPMENT.md` (including
  the release pipeline), `SETTINGS.md`, and the README. The old pages were merged rather than
  rewritten, so the field evidence and failure policy are unchanged.
- Every Windows build is started once with a temporary app folder and must write its startup line,
  so a package that cannot launch fails CI instead of being published.

### Fixed

- Pausing learning now freezes the data even when the game's sector lines settle while it is
  paused: the passes held for retiming are dropped instead of being written behind the driver's back.
- A sector timed after the fact carries the same typed outcome as one timed live, so the status line
  never falls back to matching English text.
- An unreadable `settings.json` is moved to `settings.invalid-<stamp>.json` instead of being replaced
  by defaults at the next save. If it cannot be moved, settings writes are refused for the run. The
  write is flushed to disk before the replace, and a failed write removes its temporary file.
- A data edit that hits an unreadable or blocked file is reported as a failed edit, not as a
  successful no-op.
- Non-finite settings values (`NaN`/`Infinity`) fall back to their defaults instead of being stored
  as invalid JSON.
- The overlay is a non-activating tool window: it no longer takes keyboard focus or a taskbar slot
  from the game.
- A crashed telemetry worker now says so on the HUD instead of leaving it waiting for the game.
- The settings window no longer scans the learned-data folder at startup or while it is hidden, and
  the store's issue list is safe to read from the UI thread.
- A settings-save failure is reported again after a later successful save, and a tray or overlay
  change is reflected in an open settings window instead of being undone by the next Apply.
- A second copy of the app exits instead of running a second overlay and writer.
- An empty game-process name is treated as "unknown" instead of matching the first task list row.
- The replay harness writes local timestamps, matching the game-log parser; the previous UTC
  formatting made every line look hours old outside UTC.

### Removed

- The pre-0.9 game-log parser (`Limits: car ... tyres out changed`), the connection/UUID learning it
  needed, and the `connect.txt` fixture. Only the current notification and split lines are read, so
  `parse_line` is stateless and a log that already has content is skipped as a whole instead of
  being read from the top.
- Seven expert settings that the defaults already handled: "Sound cues" (volume 0 is silent),
  "Minimum warning distance" (fixed at 35 m), the warning and brake-now tone lengths (fixed at
  90/120 ms), "Braking ends below" (now always 0.15 below the start threshold), "Skip sector if lap
  invalidated" (always on; it was a way to defeat the product's promise), and "Own runs before
  leaving reference" (fixed at 2). The telemetry rate moved to the Diagnostics tab.
- `SETTINGS_VERSION` is now 4, so a settings file from 0.5.0 or earlier is archived and the app
  starts from defaults (see [GAME_DATA.md](docs/GAME_DATA.md#files)).

## 0.5.0 - 2026-10-25

### Added

- A pre-commit configuration runs the project's lint, format, type, YAML/TOML and whitespace checks
  before a commit, and `.editorconfig` keeps editors consistent. Real fixture files are excluded
  from whitespace fixes.
- Dependabot keeps the Python dependencies and the pinned GitHub Actions current.
- A `SECURITY.md` explains private vulnerability reporting, and the issue templates now include a
  feature request and ask bug reports for the `app=`/`build=` startup line.
- A replay harness in `tests/replay.py` feeds timestamped telemetry frames and real game-log lines
  through the engine, so attribution bugs can be reproduced from a small anonymized trace.

### Changed

- Settings metadata now lives in one registry: defaults, ranges, labels, tips and tabs are defined
  once and used by the config loader, the settings window and the generated reference, so they
  cannot drift. The hidden overlay position is explicit rather than inferred.
- The overlay updates its text and styles only when the value actually changes, instead of on every
  telemetry frame.
- The installer declares its publisher/support/update URLs and product version, detects a running
  copy through a named mutex before upgrading, and closes it first. The app creates that mutex.
- The engine is now a package (`brake_trainer.engine/`) instead of one 1600-line module: session
  and storage, sector passes, sector lines, braking zones and track limits, cues and shared
  constants each live in their own file. The public import path is unchanged and behaviour is
  identical.
- Sector results now carry a typed outcome (`DropReason`/`OutcomeKind`); the driver-facing wording
  lives in one module, so the status line no longer matches English phrases to decide what to show.
  The notes and overlay text are unchanged.
- GitHub Actions are pinned to commit SHAs, and PySide6 is bounded below 7 so a major upgrade cannot
  land unreviewed.
- Dependencies are locked in `uv.lock`; CI installs the exact set with
  `uv sync --frozen --extra dev`, and a weekly Security workflow audits the lock with `pip-audit`.
- The settings window is now a `ui/settings/` package (window shell, form, diagnostics, data and
  about pages). The behaviour and the `ui.settings_window` import path are unchanged, so existing
  callers and tests keep working.

## 0.4.2 - 2026-10-25

### Fixed

- The portable zip and the installer now include the third-party licence texts referenced by
  `THIRD_PARTY_NOTICES.md` (MIT for acevo-sdk and LGPLv3 for Qt/PySide6), and the build fails if
  any licence file is missing.

## 0.4.1 - 2026-10-24

### Fixed

- The portable zip and the installer now include `LICENSE` and `THIRD_PARTY_NOTICES.md` beside the
  program, and a release build fails if either file is missing.

## 0.4.0 - 2026-10-24

### Added

- The app now uses the game's own three sectors. Their two inner lines are learned from the game's
  log and stored per track, so sector times match the game's and the sector bar marks the real
  lines. A new track settles on equal splits after three laps if the log never brings them.
- Braking cues and sector times are no longer rounded to the telemetry frame: a line or a sector
  crossing is placed at the car's interpolated position at the event's own time.
- Braking points driven before the game's lines arrive are kept and used for cues, instead of
  leaving a new track's first corners without any.
- `settings.json` and learned-data files now record the app version, a build identifier and the
  save time, and the log opens with one structured diagnostics line. A new Diagnostics tab turns
  on verbose logging of the game's track-limit signals and log lines.
- Settings -> Data lists files the app could not read, with the reason and where they were moved.

### Changed

- Track limits now invalidate exactly the sectors the game judged. The game's log, its race-cut
  pair and its one-shot lap flag are recorded against a `(lap, sector)`, so one cut drops one
  sector and says so once; a second cut in the same lap is still caught.
- Cut attribution follows the event's own position and time, so a buffered log line read a lap
  late still drops the sector it happened in. The `cut_give_back_m` setting is retired and
  `settings_version` is now 3.
- "Follow the game's log" now also brings the game's sector splits, which is why it is no longer
  only about cuts.
- A settings file from a newer build keeps its version and any keys this build does not know; a
  failed settings write is reported instead of being silent.
- A learned-data file from a newer layout, a corrupt file, or one with a different sector count is
  moved to `data\quarantine\` instead of being overwritten. If it cannot be moved, the app keeps it
  and refuses to save over it.
- A learned-data write now reports failure instead of pretending it worked: the old file is kept,
  the temporary file is removed, and the status line says the data could not be saved until a later
  write succeeds. Deleting data that cannot be removed is reported too.
- The status line says what is actually true during warm-up and while waiting for the game's lines;
  sector results show their gap to the sector's best.
- `acevo-sdk` is pinned below 0.2.0, which only releases frames after a clean lap boundary.
- Python 3.11 or newer is required (3.10 is past end of life). Pull requests and the nightly build
  run the same gates, with the tests also on Windows, so a platform-only failure is caught before
  it ships.
- A release now fails closed: it stops if the installer cannot be built, if the portable zip, the
  installer or the checksum file is missing or empty, or if a checksum does not match. The
  executable is stamped with the commit it was built from, so `build=` identifies the exact code.
- The test suite now treats warnings as errors, has a per-test timeout and enforces a coverage
  floor, so a regression in the code the tests reach fails the pull request.

### Fixed

- The sector bar's inner boundaries now sit on the game's lines instead of equal thirds, and the
  gap between segments is gone.
- A buffered log line read across a backwards start/finish wrap no longer drops a sector of the
  next lap.
- Two different track or car names that reduce to the same filename no longer overwrite each
  other's data. Deleting a run names its sector, time and braking points, so two runs with the
  same time cannot remove the wrong one.
- A cut read between the first sample after the line and the next belongs to the lap its own time
  falls in, not to the sector of the lap that ended.
- A live lap flag that drops in the frame that crosses a line no longer takes out the new sector;
  with the log on it waits for the log's own time, otherwise it stays with the sector that ended.
- A late split no longer stores a first sector that spans the start/finish line.
- Sectors that close while the app is waiting for the game's lines are timed from the kept samples
  instead of being lost.
- A car joining a track another car has already learned now takes those lines and scores from its
  first lap.
- A lap invalidated because it began in the pits no longer opens the session with "S1 won't count".
- A deleted or never-driven data entry is no longer logged as an unreadable file.
- Turning the game log on or off, or pointing it at another folder, now takes effect without
  restarting the app.
- A change to the preferred reference car, the number of runs kept per sector, or the game-log
  switch now applies to the session in progress; the borrowed braking points are looked up again
  and a lower run count removes the slower stored runs.
- A game log replaced by a larger one (the game starts a new file on every run) is read from its
  top instead of resuming at the old offset, and a line without a timestamp is skipped instead of
  being filed at the time it was read.

### Removed

- The live tyre-count feature and its two settings ("Skip sector if tyres off track" and
  "...once the lap is invalid"). The game did not publish the field in testing, and its log
  already reports every cut.
- "Sectors per lap", its automatic length/minimum/maximum, "Place sector lines on straights", the
  warm-up survey and the steering field it read.

## 0.3.11 - 2026-10-15

- Track limits now use the game's own events: the app follows the game's log (`Saved Games\ACE\Logs`),
  where every violation (all four tyres out, 2 m or more beyond the line, the rule that invalidates a
  lap) is reported. Every sector with a violation is dropped, also a second one in the same lap, which
  the lap-invalid flag cannot show. A sector that closed within a second of a violation is taken back.
  New settings: use the game's log (on) and its folder.

## 0.3.10 - 2026-10-14

- Fix: after the game invalidated a lap, a second off-track moment in a later sector of the same lap
  was not caught (the game's flag only drops once) unless all four tyres were off. Now two tyres off is
  enough to drop a sector for the rest of an invalid lap (new setting "...once the lap is invalid",
  0 turns it off). Sectors without a mistake are still kept.

## 0.3.9 - 2026-10-13

- The `.ico` stores the small sizes as plain bitmaps (PNG only at 256 px), the form Windows Explorer
  reads most reliably, and the build prints which icon it uses. Added a troubleshooting entry for
  Explorer's icon cache, which can keep showing an old icon for a rebuilt `.exe`.

## 0.3.8 - 2026-10-13

- Game exit is noticed almost instantly: the app watches the game process through a Windows handle and
  closes within a fraction of a second (it falls back to checking every second, about 2 s, if Windows
  refuses the handle). Before it took 5 to 10 seconds.
- Settings -> Data is now a tree: delete a single stored run, a whole sector, or a whole track and
  car. Deleting is applied by the running app, so a deleted entry is no longer written back when
  the app saves or quits.
- An app icon (a brake disc with a red caliper) for the windows, taskbar, tray, executable and
  installer. The taskbar shows it instead of Python's when running from source.
- GitHub Actions: pull requests get checks and a Windows build to try; every merge to `main` refreshes
  a Nightly pre-release; pushing a `vX.Y.Z` tag publishes a release with the changelog, an installer,
  a portable zip and checksums. Added `packaging/installer.iss`, `scripts/bump_version.py`,
  `scripts/release_notes.py` and `docs/RELEASING.md`.

## 0.3.7
- Fix: another car's old equal-split data used as a reference stopped a new car from getting its
  sector lines placed on the straights. Borrowed braking points are now matched by track position.
- Old equal-split data is flagged: "equal sector lines" in the overlay's summary, a "Sector lines"
  column in Settings -> Data, and a note in the log.

## 0.3.6
- Credits to the original Brake Trainer (AugGust) and acevo-sdk (Gleb Zverinskiy).
- Clear notice that the project is largely AI-written ("vibe coded"), an About page, an AI
  contribution policy and a pull request template.

## 0.3.5
- Sector lines are placed on straights instead of equal splits: the warm-up lap surveys where the
  corners are, so a corner is never cut between two sectors (a corner on a line used to go
  unlearned in roughly 1 session in 10). Lines are stored per track and shared between cars.
- The status line under the sector bar now shows what matters right now (sector that will not
  count, learning paused, warm-up, last sector result, reference car, or a summary).
- Documentation, license, changelog, settings reference and CI.

## 0.3.4
- Warm-up laps: the first lap after leaving the pits (and after starting the app) is not learned.
  Cues still play. Configurable, 0 turns it off.
- The overlay opens at the top centre of the main screen; "Reset position" in the menus.

## 0.3.3
- A sector is not saved if the game invalidates the lap during it, or if all four tyres were off
  the track at some point.

## 0.3.2
- Learning can be paused (overlay button, tray menu, settings). Cues and sector colours keep
  working, nothing is saved or changed.

## 0.3.1
- Fully transparent HUD (optional background), smaller distance number.
- F1-style sector indicator (grey / yellow / green / purple), in three groups with sub-sectors.
- Telemetry rate default raised to 60 Hz.

## 0.3.0
- Rewritten as a PySide6 application: live overlay window, settings window, tray icon.
- Project structure, tests (pytest), lint (ruff), types (mypy), Windows executable build.
- Per-sector learning, reference car for new cars, automatic restart of telemetry, closes with
  the game.

## 0.1 - 0.2 (script)
- Single-file prototype: audio cues from learned braking points, three sectors, best-run saving,
  borrowed reference car, closes when the game exits, workaround for the SDK's idle timeout.
