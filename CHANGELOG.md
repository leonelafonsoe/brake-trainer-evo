# Changelog

All notable changes to this project. Versions before 0.3 were a single-file script.

## Unreleased

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
