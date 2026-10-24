# Changelog

All notable changes to this project. Versions before 0.3 were a single-file script.

## Unreleased

- Fix: the sector bar drew its two inner boundaries at equal thirds of its width, whatever the
  game's own sector lines were. On tracks with unequal sectors that put them hundreds of metres
  from the real line (the Red Bull Ring's S1/S2 line is at 26% of the lap, Spa's S2/S3 at 72%), so
  the bar looked as if the sector changed at a corner it did not. Each segment now spans its
  sector's real share of the lap, with the gap between two centred on the game's line.
- Fix: a buffered log line read between two samples that wrap the start/finish line *backwards*
  within one lap number (a reset, or the car crossing the line the wrong way) was placed at a
  position in the next lap while keeping the old lap's label, dropping a sector that had not been
  driven yet. It now falls back to the earlier sample, as it already did for a forward wrap.
- The live tyre-count feature and its two settings ("Skip sector if tyres off track" and
  "...once the lap is invalid") are removed. In testing the game did not publish
  `number_of_tyres_out`, and the game's log already reports every cut; the settings only added a
  second, unreliable path that could drop a sector the game did not judge. Existing settings files
  still load: the two keys are ignored.
- The app version and save time are now written into `settings.json`, every learned-data file and
  the log, so a file shared for support can be matched to the build that wrote it. The loaders
  ignore these fields, so files from older and newer builds still load.
- A settings file from a newer build is no longer rewritten with this build's settings version:
  its version is left alone (with a warning in the log), so the next run of the newer build does
  not migrate it a second time.
- Fix: a cut was dropped in the sector where the game's report landed, not the one where it
  happened. The game gives the driver 500 m to hand back the time a cut gained and writes the
  report (and drops `is_valid_lap`) only after that window, so a cut at the Ascari entry was
  reported at the exit, just past the S2/S3 line, and S3 was dropped instead of S2; a cut before
  Lesmo did the same to S2. Reports are now read back by the game's 500 m window
  (`cut_give_back_m`, default `500`). A settings file from an older version, which stored the old
  `0` default, is migrated once; a deliberate `0` in a current file still trusts the report
  position.
- Pin `acevo-sdk` below 0.2.0. That release only releases captured frames after it sees a clean lap
  boundary, so the live overlay stayed on "Game running — not in a session" until a lap was
  completed. The app needs every frame; lift the pin when the SDK offers a live-frame path again.
- Sector lines and sector times are no longer quantised to the telemetry frame. A game-log split is
  placed at the car's **interpolated** position at the split's own timestamp (the previous code used
  the last frame at or before it), and a sector now closes at the interpolated crossing instead of at
  the first frame after the line. At 60 Hz and racing speed a frame is about a metre: the lines sat up
  to a frame early because the old code used the last frame at or before the split, while a sector
  time, measured between the first frames after its two lines, could be out by up to a frame in either
  direction. Interpolating removes that quantisation; the remaining error is the interpolation
  residual described in `docs/TELEMETRY.md`, usually a few tenths of a metre rather than a guaranteed
  bound. A game-log split is only placed by interpolating between a
  normal pair of samples: if the pair wraps the start/finish line inside one lap, or jumps more than
  5% of a lap (a reset or teleport), the split falls back to the earlier sample rather than inventing
  a position the car never had. Verbose logging now also audits every later split against the learned
  line (`splits: audit index 0 ... the app's line was crossed 3.7 ms / 0.2 m after the game's`),
  which is how a line placement can be checked from an app log plus the matching game log.
- Fix: a cut read between the first sample after the start/finish line (which still carries the old
  lap number) and the next was attributed to S1 of the lap that had just ended, greying that sector
  and taking back its stored run. It now belongs to the lap its own time falls in: at the line that
  is S1 of the new lap, and a give-back window reads it back into S3 of the lap that just ended.
- Fix: a buffered split read that arrived after the car had already crossed the game's line kept the
  pass in progress on the start/finish line, storing a first sector that spanned the lap line to the
  read position - too long by the distance already driven. It is now timed from the game's own line,
  and a crossing asked for outside the two samples falls back to the current sample, not a clamp.
- Track limits now invalidate exactly the sectors the game judged. Every signal is recorded against a
  `(lap, sector)`, so a cut seen live by the race-cut pair or the lap flag and again in the log (or
  re-read after a restart) drops one sector and says so once, while two cuts in different sectors of
  the same lap each drop their own. The old two-second window could swallow a genuinely different cut
  reported moments after another. Off-track results read `not counted · <reason>` in the log, and the
  setting is now called "Follow the game's log" because it also brings the game's sector splits.
- Fix: the sectors that close while the app is still waiting for the game's sector lines are no longer
  lost. The game buffers its log, so on a fresh track the lines can be read a lap or more after the
  sectors that needed them; the samples already kept for late cuts also say when the car crossed each
  line, so those sectors are timed and stored the moment the lines arrive (never for a sector the game
  took out, and only while the crossings are still in the five minutes of samples). The sector in
  progress is moved onto the game's line the same way instead of being dropped, which is what "the
  lines were learned mid-sector" now means only when a reset or a long pause took the crossing away.
  If no split ever arrives, the equal splits become the permanent lines and the laps driven while
  waiting are timed on them at that point, so the fallback does not cost those laps either.
- The app now uses **the game's own sectors**. Every lap is scored in three, and the two inner lines
  are learned from the game's log: each timed lap writes a split as the car crosses a line
  (`Received split: ... index 0/1/2`, the end of the first, second and third sector), and the car's
  position at that line's own timestamp is the line - the same position-and-time attribution the cut
  reports already use, since the game buffers this log too. Both lines have to come from one lap and
  land where a sector line plausibly sits, which keeps a teleport or a reset from placing one. Until the
  lines are known no lap is counted, because a run timed between lines that then move would be filed
  under the wrong sector; if no split arrives (the log not followed, or a build that does not write
  them) the app settles for equal splits after three laps and says so. This replaces the warm-up survey
  of braking points and steering and the whole line-placement search: no corner is ever split, because
  the game's lines sit at corner exits (at Monza, just before the Roggia and Ascari braking points), and
  the app's sector times are now the game's own. "Sectors per lap", its automatic
  length/minimum/maximum and "Place sector lines on straights" are gone from Settings -> Sectors, along
  with the steering field the survey read.
- Fix: a car driven for the first time on a track another car has already driven took the sector lines
  from it but then still counted nothing until the game's log repeated them - and, after three laps,
  said it had fallen back to equal splits. The lines are the track's, not the car's, so an entry now
  takes them and keeps them, and scores from its first lap.
- Fix: a lap the game invalidates because it began in the pits no longer opens the session by telling
  the driver that its first sector will not count. That sector is a warm-up drop anyway, so the drop
  changes nothing; it is only written to the log now, and the reason is kept on the sector's own result
  ("S1 not counted · warm-up lap"). "The game invalidated the lap at ..." is said only when the sector
  it takes out would otherwise have counted.
- Result and track-limit messages say the same thing in fewer words: a run outside the kept times is
  "not kept" rather than "not faster", a dropped sector is "won't count" rather than "will not count",
  and a position is just "at 44%" rather than "at 44% of the lap". A sector that already will not count
  - a warm-up lap, the lines still being found, or one already reported as not counted - no longer gets
  a second cut announcement; its own result keeps the reason.
- A deleted or never-driven data entry is no longer logged as an unreadable file when the app reads it
  back; it is simply empty, as it was before the first run.
- Fix: the lap the sector lines are learned on no longer loses the sector it had just started. A new
  track and car begins on stand-in equal splits (the game's own lines can only be read from its log),
  and the game buffers that log, so the read that brings them often lands a moment after the car crossed
  the start/finish line: the sector just begun started on that line, which both layouts share, and ends
  on one of the game's lines, so it is timed correctly and counts. A sector that was already part-way
  through had started on a stand-in equal line, somewhere else than the game puts its own, so its time
  is dropped - now saying "not counted · the lines were learned mid-sector" instead of blaming the pit
  lane or a reset for it.
- The braking points driven before the sector lines arrive are now kept. The game buffers its log, so
  the lines can turn up a lap or more after the sectors that needed them, and those sectors could not be
  timed. Where braking started is a position on the track and needs no sector line to be useful, so it
  is now held on to (as `early_onsets` in the data file, one entry per pass) and places the cues at once
  instead of leaving the first corners of a new track without any until a sector had been timed in full.
  Each kept pass counts as one run, so once a couple of laps have been timed the runs that count
  out-vote it and it stops mattering. Warm-up laps and laps the game invalidated add nothing.
- Fix: the overlay no longer opens a session with "S1 won't count · lap invalidated" when that sector
  was never going to count anyway (a warm-up lap, or the lines still being found) and the flag stays on
  the sector's own result line. The status line says what is actually true - "Warm-up lap · not
  learning", then "Waiting for the game's sector lines" once the warm-up laps are over. That waiting is
  the app's, not the driver's, so it is no longer dressed up as a learning state: learning starts when
  both are settled, the warm-up laps are done and the game's lines are known. The big distance readout
  follows the same rule - "warm-up", "waiting…", "paused" or "learning…" instead of always claiming to
  learn whenever it is empty.
- Sector results now say how far off the sector's best they were: "S2 39.17 s · good (+0.33 s)",
  "S2 48.85 s · slower (+10.01 s)", and "best (-0.45 s)" for a new best, measured against the run
  it replaced. The log line carries the same number. The colours themselves are unchanged: they
  are a rank (green = made your fastest `top_runs`, purple = new best), not a time threshold.
- Fix: every off-track moment is dropped from the sector it happened in, including a second one in a
  lap the game has already invalidated. The game reports each cut in its log, once per cut
  (`Adding notification UINotificationType_SessionPenalty`); that notification is now the signal the
  app follows, and it is the only source that shows every cut — the "lap valid" flag drops once per
  lap. The live "race cut" pair still drops a sector where a build publishes it. New settings:
  "Follow the game's log" and "Game log folder".
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
  ("S3 of the last lap won't count · cut") for a few seconds: there is no colour left on the bar to
  grey, and the stored run it takes back leaves no trace there either.
- The "the game reported no off-track for this invalidation" warning is only shown when the game log
  is not being followed: with the log on, every cut is in it (a few seconds later), so the fallback is
  noted in the debug log instead of warning about a limitation that does not apply.
- Fix: a cut report can arrive after the sector it is about. When it does, the app still drops the
  right sector: it reads the sector back from the report by the configured give-back distance and
  takes back the run if that sector was already saved, restoring the list it replaced. The clean
  sectors in between are kept.
- Verbose (debug) logging for troubleshooting: a new Settings -> Diagnostics tab turns it on (also
  `--debug` on the command line or `BRAKE_TRAINER_DEBUG=1`), and logs the game's track-limit signals at
  every change (the race-cut pair, the lap flag and the timing invalid flag) and every cut read from
  the game's log, with the position, the sector
  it was reported in and the sector it was attributed to, plus the telemetry regions the SDK attached
  to. "Open log folder" opens the log for sharing. Off by default.

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
