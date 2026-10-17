# Changelog

All notable changes to this project. Versions before 0.3 were a single-file script.

## Unreleased

- The give-back read-back distance is now 150 m by default, not 500 m, and every cut message names
  the sector it dropped ("S4 will not count") on the lap being driven as well as on an earlier one.
  Measured on track, the game reports a cut around the corner it happened in (a Monza cut in the
  Ascari chicane came back at the corner's exit), where 500 m put the named spot out on the straight
  before it; the named position is now where the driver felt the off. Which sector a cut lands in is
  unchanged for the logs checked. Tune it in Settings -> Sectors -> "Cut give-back window".
- Fix: every off-track moment is dropped from the sector it happened in, including a second one in a
  lap the game has already invalidated. The game reports each cut in its log, once per cut
  (`Adding notification UINotificationType_SessionPenalty`); that notification is now the signal the
  app follows, and it is the only source that shows every cut — the "lap valid" flag drops once per
  lap. The live "race cut" pair and the count of tyres off the track still drop a sector where a build
  publishes them. New settings: "Follow the game's log for cuts" and "Game log folder".
- Fix: the game buffers its log (a few KB, flushed when full), so a cut can reach the app a minute
  after it was written - or after the lap it belongs to has ended - and one read can bring a whole
  lap's cuts at once. Each line's own time is now what a cut is attributed from - the car's position
  *then*, and the lap that time falls in, taken from a short history of recent samples - instead of
  the position when the line was read. That keeps every cut in the sector it happened in when several
  arrive together, and keeps a late one out of the lap being driven: the run its own lap saved is
  taken back, and the sector of the same number in the current lap is left alone. Before, later cuts
  in a delayed read were folded into the first and lost, a late cut was dropped one sector too far on,
  and a cut read after its lap had ended greyed the wrong lap's sector. The verbose log now shows the
  read lag and the lap per cut, and names a cut it folded away because the lap flag had already
  caught it - even when the same batch carries later cuts - so every notice in the game's log can be
  accounted for.
- A cut the log reports for a lap the sector bar has already moved past is named on the status line
  ("S6 of the last lap won't count · cut") for a few seconds: there is no colour left on the bar to
  grey, and the stored run it takes back leaves no trace there either.
- The "the game reported no off-track for this invalidation" warning is only shown when the game log
  is not being followed: with the log on, every cut is in it (a few seconds later), so the fallback is
  noted in the debug log instead of warning about a limitation that does not apply.
- Fix: the game only reports a cut at the end of its give-back window, so the report arrives after the
  sector it is about. The app reads the sector back from the report by that distance
  (Settings -> Sectors -> "Cut give-back window"; `0` uses the sector the report arrives in) and takes
  back the run if that sector was already saved, restoring the list it replaced. The clean sectors in
  between are kept.
- The live count of tyres off the track is used as well, where the game publishes it (all four while
  the lap is valid; the lower "...once the lap is invalid" count afterwards). In testing the game did
  not publish it at all, so the log notification is what does the work.
- Verbose (debug) logging for troubleshooting: a new Settings -> Diagnostics tab turns it on (also
  `--debug` on the command line or `BRAKE_TRAINER_DEBUG=1`), and logs the game's track-limit signals at
  every change (the race-cut pair and the live tyre count, where the game publishes them, the lap flag
  and the timing invalid flag) and every cut read from the game's log, with the position, the sector
  it was reported in and the sector it was attributed to, plus the telemetry regions the SDK attached
  to. "Open log folder" opens the log for sharing. Off by default.

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
