# Changelog

All notable changes to this project. Versions before 0.3 were a single-file script.

## Unreleased

## 0.3.11 - 2026-10-15

- Track limits now use the game's own events: the app follows the game's log (`Saved Games\ACE\Logs`),
  where every violation (all four tyres out, 2 m or more beyond the line, the rule that invalidates a
  lap) is reported. Every sector with a violation is dropped, also a second one in the same lap, which
  the lap-invalid flag cannot show. A sector that closed within a second of a violation is taken back.
  New settings: use the game's log (on) and its folder.
- The "...once the lap is invalid" tyre limit added in 0.3.10 is off by default now: it went beyond the
  game's own rule. (If you ran 0.3.10, your saved settings keep the old value 2; set it to Off.)

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
