# Game data and files

How the app gets its data from Assetto Corsa EVO, the quirks to know about, and the files it writes.
The user-facing behaviour is in [GUIDE.md](GUIDE.md); the design reasons are in [DESIGN.md](DESIGN.md).

The game publishes telemetry through shared memory. The app reads it with
[`acevo-sdk`](https://github.com/glebulon/acevo-sdk) (MIT licensed, early alpha). It only reads that
telemetry, and the game's own log file for the cuts the telemetry cannot show. It never writes to the
game or its files.

## Telemetry

### Fields used

| Value | SDK source | Used for |
| --- | --- | --- |
| Track position (0..1) | `graphics.normalized_car_position` | Where you are on the lap |
| Brake pedal (0..1) | `physics.brake` | Braking events |
| Speed | `physics.speed_kmh` | Braking events, cue timing |
| Track / car name | `static.track`, `graphics.car_model` | Keys for the stored data |
| Track length | `static.track_length_m`, or `graphics.lap_length_km` | Metres from positions |
| In the pit lane | `graphics.is_in_pit_lane` | Not learning in the pits; warm-up reset |
| Lap still valid | `graphics.is_valid_lap` | Skipping the first sector the game invalidates |
| Race cut (off-track) | `graphics.race_cut_gained_time_ms`, `graphics.distance_to_deadline` (raw graphics block) | Skipping the sector where an off-track happened |
| Cuts reported after the fact | `Saved Games\ACE\Logs`: `UINotificationType_SessionPenalty` | Skipping the sector each cut happened in |
| The game's sector lines | `Saved Games\ACE\Logs`: `Received split: ... index 0/1/2` | Where the three sectors begin and end |
| Timestamp | frame timestamp | Sector times |

**Position source.** The SDK also returns a position estimated from the physics data
(`normalized_position_source: physics_tyre_z`). That one is dead-reckoned and can jump, so the app
uses the game's own value from the graphics block. Frames without a track or car name (menus,
loading) are ignored.

### Sector lines

Every lap is scored in three sectors, and the shared memory carries no sector data at all in this
build (`current_sector_index` exists only in the older AC/ACC layout the app does not use), so the
lines come from the game's log. Each split is written as:

```
... [gameplay] [info] Received split: isStart false, isEnd false, index 1
```

`index` is the sector that just ended (0, then 1, then 2 for the start/finish line, which teaches
nothing). The line's own timestamp is when the car crossed it, so the app takes the car's position at
that time - the same history a late cut is attributed from. The position is interpolated between the
two telemetry frames around the timestamp; the previous code took the last frame at or before the
split, so its lines were always up to a frame (about a metre at racing speed) early, while the
nearest frame could be early or late. An out-lap writes the same `Received split` line, and teaches
the lines just as well: they belong to the track, not to the lap. What is left has to come from one
lap - which a reset or a teleport in between breaks - and land where a sector line plausibly sits
(the first in the first 60% of the lap, the second in the last 60%, 5% clear of both ends).

Until both lines are known no live sector is counted: a run is timed *between* two lines, so
re-filing it under different ones would be wrong. A fresh entry shows "Waiting for the game's sector
lines"; if no split arrives within three laps the app settles for equal splits and says so (timing
the laps driven meanwhile on them). The sectors that closed while waiting are not lost - the samples
say when the car crossed the lines, so they are timed once the lines are known - and the sector in
progress is moved onto the game's line the same way. The lines are then saved with the track data
(`boundaries`), borrowed by the other cars on that track, and never moved again - deleting the entry
is what learns them again. The user-facing version is in
[GUIDE.md](GUIDE.md#where-the-sector-lines-are).

#### Checking where a line ended up

The game's split is also the reference for the learned line: its timestamp is when the car crossed
it. With verbose logging on, every later split writes one line to the app log:

```
splits: audit index 0 at 32.1% (lap 4, 214 km/h): the app's line was crossed 3.7 ms / 0.2 m after the game's
```

`after` means the learned position is slightly further round the lap than the game's line, `before`
the other way. The expected value is usually well under one telemetry frame; at 60 Hz that frame is
about a metre at 200 km/h, and the audit examples are a few tenths of a metre. It is not a guarantee:
the residual grows with speed and with any non-linearity in the reported position. A value that stays
much larger points at a clock difference between the game log and the telemetry, or at a log line
written after the car had already crossed the line.

The game's log alone cannot answer this: it has the split *times* but not the car's position on the
track. The position comes from telemetry, so an app log with verbose logging and the matching game
log are what make the check possible.

### Track limits

Track limits follow the game, using its own signals:

- **The game's log** (game build 0.5+) records one HUD notification per cut:
  `Adding notification UINotificationType_SessionPenalty`. It is the only *per-excursion* signal the
  game publishes — the shared memory cannot show a second cut in a lap it has already invalidated.
  The warning line that follows it (`false {PENALTY_CLEARED_KEY}` in the current build) describes the
  notification's HUD text; it is not a second event. The app follows the newest file in
  `Saved Games\ACE\Logs` (Settings: *Game log folder*) and drops the sector each cut happened in.
- **`graphics.is_valid_lap`** is the game's verdict on the lap. It is a *state*: it drops when the
  game invalidates the lap and stays down until the lap ends, so on its own it marks only the first
  cut of a lap. Kept as a fallback for a build whose log the app cannot read.
- **`graphics.race_cut_*`** (the *race-cut pair*: time gained and distance left to give it back)
  drops the sector while the off-track is under way, where the game publishes it. The SDK does not
  surface these fields, so they are read at fixed offsets in the raw graphics block; a block that
  shifts in a game update would otherwise feed arbitrary numbers to the engine. A pair is therefore
  used only when the gain is `1..60 000 ms`, the give-back distance `0..5 000 m` and the delta is
  finite; anything else is read as no cut, by both the reader and the engine. The log is the
  authoritative per-cut signal; the pair is a live fallback for a build that fills it in.

These signals overlap: the same cut can be seen live by the race-cut pair or the lap flag and again in
the log. Each invalidation is recorded against a `(lap, sector)`, so the first signal to reach a
sector acts and the others are folded into it — one cut drops one sector and is announced once —
while two cuts in different sectors of the same lap each drop their own.

**Attributed where the game reports it.** A cut notification is written where the game judged the
cut, and the lap flag drops at the same moment. The app drops the sector at that event's own
position. This matches the field logs: at Monza the notifications and lap-flag drops sit at natural
corner exits — Roggia at 36–37%, Lesmo at 50.6%, Ascari at 67–68% and curve 10 at 71–73% — rather
than a fixed distance behind them. In particular, a cut at curve 10 (71–73%) is in S3, past the
65.67% S2/S3 line; it is not read back into S2. If the sector a cut lands in was already saved, its
run is taken back (`S3 had its stored run taken back`); if it is still in progress, the sector is
marked as not counting (`S3 won't count · off track`).

#### Field validation

A clean field session on **Monza / Ferrari 296 GT3** (app 0.5.0, game 0.9.1) was used to check the
premise with real timestamps. Five deliberate cuts were driven: Lesmo at 50.6% and 51.4% (S2), Ascari
at 68.3% (S3, just after the 65.7% S2/S3 line), Parabolica at 95.7% (S3, near the start/finish seam)
and a second Ascari cut in the same lap as the 51.4% Lesmo cut. All five were attributed to the
expected sector; the late reads were also attributed to the correct lap.

Across 18 split audits, the interpolation residual was **median 3.75 ms / 0.25 m**, **maximum
15 ms / 0.9 m**, with both `before` and `after` signs. That is below one telemetry frame at these
speeds and shows no systematic clock offset, so no time-offset setting is applied. The test table in
`tests/test_cut_attribution.py` keeps the 50.6%, 51.4%, 68.3% and 95.7% cases as regressions.

#### Read from the line's own time

The game buffers this log (a few KB, flushed when full), so a line can reach the file a minute after
it was written - or after the lap it belongs to has ended - and one read can bring a whole lap's cuts
at once. Every line carries its own timestamp, so the app attributes each cut from the car's position
*at that time* — not from wherever the car is when the line is finally read. The sampled history it
looks that up in records the lap too, so a cut is dropped in the lap it happened in and never in the
sector of the same number in the lap being driven now. When its lap is over the colours for it are
gone from the sector bar, so the status line names it instead ("S3 of the last lap won't count ·
cut"). The debug log shows the read lag and the lap per cut (`... written at ... (read 12.3 s later,
1 lap back), car at 49.7% (S3) ...`).

Only the current notification and split lines are read: the older tyre-count format (`Limits: car ...
tyres out changed`) and the connection lines that named the player's car are no longer parsed. An
infraction the game judges from something it does not expose (no cut in its log and no race cut)
cannot be pinned to a sector. With the log being read, every cut is in it, so the app stays quiet and
notes the fallback only in its debug log; with the log switched off it warns, and can only drop the
sector where the flag dropped.

### Behaviours worth knowing

- **Idle timeout.** The SDK stops capturing after 120 s of standing still before the first lap
  (sitting in the pits, waiting in an online lobby). The app disables that timeout.
- **Watchdog.** If capture stops for any other reason, the app logs
  `Telemetry stopped (<reason>); restarting`, waits two seconds and starts a new capture. The sector
  in progress is discarded so a gap cannot produce a wrong sector time.
- **Rate.** 60 Hz by default (5-60 in Settings -> Diagnostics). Sector times can be finer than one
  sample: a line crossing is interpolated between the two frames around it rather than snapped to
  one. The residual is the game log's millisecond timestamp resolution (a few cm at racing speed)
  plus the car's speed changing across a sample (and any non-linearity in the reported position),
  which is normally well under the sample interval. The app can read faster than the game publishes
  shared memory, though, so extra samples may be duplicates: a higher read rate can smooth live data
  only up to the game's own update rate, and cannot refine a crossing beyond it. A change applies
  when telemetry next starts, not to the live capture.
- **Game exit.** While waiting for the game, the app runs `tasklist` every 3 seconds and looks for a
  process whose name contains `assettocorsaevo` (case-insensitive). Once it finds the game it opens a
  Windows handle to that process and checks it every poll, so the exit is noticed within a fraction
  of a second and the app closes straight away (after saving). If Windows will not give the app a
  handle (for example because of anti-cheat protection), it falls back to running `tasklist` every
  second and closes after two checks without the game, about 2 seconds. If `tasklist` cannot be run,
  the app never closes itself.

### Caveats

- The game is in Early Access and the SDK is alpha: fields can change between updates. All SDK
  access is in `telemetry.py` and all log parsing in `gamelog.py`, so a change should only touch
  those files.
- The game does not always publish the live race-cut pair: in testing it stayed empty while the game
  invalidated laps. The game's log is what reports each cut; the pair is kept as a fallback for a
  build that does publish it. If sectors stop counting unexpectedly, turn on verbose logging and
  check the log.
- If the app cannot find the game log it says so and falls back to the lap flag alone (one cut per
  lap). Point it at the right folder in Settings: *Game log folder*.
- Whether telemetry readers are acceptable in online sessions is the game's and server's call; check
  the game's terms and anti-cheat policy before using any tool online.

## Files

Everything is stored per user in `%APPDATA%\BrakeTrainerEvo\`:

| Path | Content |
| --- | --- |
| `settings.json` | Your settings (see [SETTINGS.md](SETTINGS.md)), the overlay and settings-window position, and the version that wrote the file |
| `settings.invalid-<stamp>.json` | A settings file this build could not read, kept instead of overwritten (see below) |
| `settings.version-<n>-<stamp>.json` | A settings file from another layout, kept instead of migrated (see below) |
| `data\<track>__<car>.json` | What was learned for one track and car, with the version that wrote it. A colliding name adds `--<hash>` (see below) |
| `data\quarantine\` | Files this build could not read, kept instead of overwritten (see below) |
| `brake_trainer.log` | Log (rotated, about 1 MB x 3), starting with one diagnostics line: app version, build, settings/data versions, log path and verbose state |

Set the environment variable `BRAKE_TRAINER_HOME` to use another folder (handy for testing).

### File names

`<track>` and `<car>` are readable slugs of the names stored inside the file: punctuation becomes
`_`. The identity is the `track` and `car` in the JSON, not the filename. If two different names
reduce to the same slug (`Car A` and `Car/A` both become `Car_A`), the colliding file gets a short
hash suffix (`Monza__Car_A--1a2b3c4d5e6f.json`), so one entry can never overwrite another. Files
written by older builds have no suffix; they still load and are updated in place. Do not rename the
files by hand: the app finds an entry by the names inside it.

### Settings compatibility

`settings.json` records a `settings_version`. There are no migrations: a file whose version is not
the one this build writes (including a file with no version, such as 0.3.x) is moved to
`settings.version-<n>-<stamp>.json` beside it and the app starts from defaults. A file from a newer
build is treated the same way, so this build never rewrites a layout it does not understand.

Writes are atomic: the new file is written to a temporary file, flushed to disk and only then
replaces the old one; a failed write keeps the previous file and removes the temporary one. If the
file cannot be written, the change still applies for the session and the app shows a warning instead
of failing silently.

A settings file that cannot be parsed is **not** overwritten. It is moved to
`settings.invalid-<stamp>.json` beside it, and the app starts from defaults. If the file cannot be
moved (for example it is locked), writes are disabled for the rest of the run rather than destroying
it.

### Learned data format

```json
{
  "app_version": "0.5.0",
  "build": "2983a85ac7d3",
  "saved_at": "2026-10-24T12:00:00+00:00",
  "version": 1,
  "track": "Monza",
  "car": "Ferrari 296 GTB",
  "n_sectors": 3,
  "boundaries": [0.3205, 0.6324],
  "sectors": [
    [ {"t": 18.012, "onsets": [0.0431]}, {"t": 18.244, "onsets": [0.0436]} ],
    [],
    ...
  ],
  "early_onsets": [ [0.1762], [0.4823] ]
}
```

- `app_version`, `build` and `saved_at`: the version, the exact code and when it was saved (UTC).
  `build` is the source checkout's git revision (`-dirty` when it had uncommitted changes), the
  commit baked into a packaged executable, or the value of `BRAKE_TRAINER_BUILD` when one was set.
  These fields are for support and debugging and are ignored when the file is loaded, so files from
  older and newer builds still load. `settings.json` carries the same three fields.
- `version`: the learned-data format version (`1`), separate from the app version. Unlike
  `app_version`, it decides whether the data can be read: a file written by a newer layout is moved
  to `data\quarantine\` (with a warning in the log) and a fresh entry starts, so the newer file is
  never overwritten by an older build. Files with an older version still load.
- `boundaries`: the `n_sectors - 1` inner sector lines (0..1). They are the game's own sector lines,
  learned from its log (see [DESIGN.md](DESIGN.md)); `null` means they have not been learned yet, so
  equal splits are in use - either a fresh entry or data saved by a build that did not read the
  game's splits. Settings -> Data shows which kind each entry is. The lines are the track's, not the
  car's, so an entry here is copied from another car's file on the same track as soon as it is
  opened, and only a track no car has learned yet waits for the log. To learn the lines again,
  delete every entry on the track and drive a lap.
- `sectors`: one list per sector, fastest run first. Each run has its time `t` in seconds and the
  track positions `onsets` where braking started in that run. Runs are sorted on load. A run with a
  non-positive or non-finite time, or an onset outside 0..1, is treated as corrupt: the file is
  quarantined rather than used.
- `early_onsets`: positions where braking started on the passes that could not be timed because the
  sector lines were still being found, or had just changed under the car - one list per pass. Their
  times are worthless (the lines they would use are not known), but they are where the corners are,
  and on a new track they are all the cues there are until a sector has been timed. They vote as one
  run each, so the counted runs out-vote them as they arrive; when the pass they came from is
  retimed, its timed run carries them and the stand-in entry is removed. A sector the game
  invalidated, or one whose crossings are no longer in the kept samples, is never stored from its
  stand-in entry.
- Files whose `n_sectors` does not match the app's sector count (3) are moved to `data\quarantine\`
  and a fresh entry starts, rather than overwritten: older files can hold a different number of
  sectors. If a file cannot be moved (for example it is locked), the app keeps it in place and
  refuses to save over it; Settings -> Data marks it read-only.
- If a learned-data file cannot be written (the disk is full, or the folder is read-only), the
  previous file is kept, the half-written temporary file is removed, and the status line says the
  data could not be saved until a later write succeeds. A failed delete is reported the same way, so
  Settings -> Data never claims something was removed when it was not.

### Deleting learned data

Settings -> Data sends one delete for the selected row. A run is named by its sector, its time and
its braking points (`onsets`); the time alone is not enough because two runs can share one. If the
entry changed since the tab was drawn and the named run is no longer there, the delete does nothing
rather than removing a different run: refresh and try again. Deleting an entry removes its file and
any older duplicate holding the same track and car.

### Housekeeping

- **Delete part of the data**: Settings -> Data shows each track and car as a tree: entry, then its
  sectors, then the runs kept for each sector. Select a single run (for example a time you got in a
  slipstream), a whole sector, or a whole entry, and press "Delete selected". Deleting an entry or a
  sector asks for confirmation. The change is applied by the running app itself, so it is not undone
  by the app saving its own copy.
- **Start over**: delete the files in `data\`. Files the app could not read are kept under
  `data\quarantine\`; delete those too if you do not need them for support.
- **Reset settings**: delete `settings.json` (and any `settings.invalid-*.json` or
  `settings.version-*.json` left by a file the app could not use).
- **Share or back up data**: copy the files. They are plain JSON.
