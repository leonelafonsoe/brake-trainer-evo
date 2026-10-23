# Telemetry notes

How the app gets its data from Assetto Corsa EVO, and the quirks to know about.

The game publishes telemetry through shared memory. The app reads it with
[`acevo-sdk`](https://github.com/glebulon/acevo-sdk) (MIT licensed, early alpha). It only reads:
that telemetry, and the game's own log file for the cuts the telemetry cannot show. It never writes
to the game or its files.

## Fields used

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
| Tyres off track | `physics.number_of_tyres_out` | Skipping any sector with enough tyres off |
| Cuts reported after the fact | `Saved Games\ACE\Logs`: `UINotificationType_SessionPenalty` | Skipping the sector each cut happened in |
| The game's sector lines | `Saved Games\ACE\Logs`: `Received split: ... index 0/1/2` | Where the three sectors begin and end |
| Timestamp | frame timestamp | Sector times |

**Position source.** The SDK also returns a position estimated from the physics data
(`normalized_position_source: physics_tyre_z`). That one is dead-reckoned and can jump, so the app
uses the game's own value from the graphics block. Frames without a track or car name (menus,
loading) are ignored.

## Sector lines

Every lap is scored in three sectors, and the shared memory carries no sector data at all in this
build (`current_sector_index` exists only in the older AC/ACC layout the app does not use), so the
lines come from the game's log: each split is written as

```
... [gameplay] [info] Received split: isStart false, isEnd false, index 1
```

`index` is the sector that just ended (0, then 1, then 2 for the start/finish line, which teaches
nothing). The line's own timestamp is when the car crossed it, so the app takes the car's position at
that time - the same history a late cut is attributed from. The position is interpolated between the
two telemetry frames around the timestamp; taking the nearest frame would place the line up to a
frame (about a metre at racing speed) early or late. An out-lap writes the same `Received split`
line, and teaches the lines just as well: they belong to the track, not to the lap. What is
left has to come from one lap - which a reset or a teleport in between breaks - and land where a
sector line plausibly sits (the first in the first 60% of the lap, the second in the last 60%, 5%
clear of both ends).

Until both lines are known no live sector is counted: a run is timed *between* two lines, so re-filing
it under different ones would be wrong. A fresh entry shows "Waiting for the game's sector lines"; if no
split arrives within three laps the app settles for equal splits and says so (timing the laps driven
meanwhile on them). The sectors that closed while waiting are not lost - the samples say when the car
crossed the lines, so they are timed once the lines are known (see below) - and the sector in progress
is moved onto the game's line the same way. The lines are then saved with the track data
(`boundaries`), borrowed by the other cars on that track, and never moved again - deleting the entry is
what learns them again.

### Checking where a line ended up

The game's split is also the reference for the learned line: its timestamp is when the car crossed
it. With verbose logging on, every later split writes one line to the app log:

```
splits: audit index 0 at 32.1% (lap 4, 214 km/h): the app's line was crossed 3.7 ms / 0.2 m after the game's
```

`after` means the learned position is slightly further round the lap than the game's line, `before`
the other way. The expected value is well under one telemetry frame; at 60 Hz that frame is about a
metre at 200 km/h. A value that stays much larger points at a clock difference between the game log
and the telemetry, or at a log line written after the car had already crossed the line.

The game's log alone cannot answer this: it has the split *times* but not the car's position on the
track. The position comes from telemetry, so an app log with verbose logging and the matching game
log are what make the check possible.

## Track limits

Track limits follow the game, using its own signals:

- **The game's log** (build 0.5+) records one HUD notification per cut:
  `Adding notification UINotificationType_SessionPenalty`. It is the only *per-excursion* signal the
  game publishes — the shared memory cannot show a second cut in a lap it has already invalidated.
  The app follows the newest file in `Saved Games\ACE\Logs` (Settings: *Game log folder*) and drops
  the sector each cut happened in.
- **`graphics.is_valid_lap`** is the game's verdict on the lap. It is a *state*: it drops when the
  game invalidates the lap and stays down until the lap ends, so on its own it marks only the first
  cut of a lap. Kept as a fallback for a build whose log the app cannot read.
- **`graphics.race_cut_*`** (the *race-cut pair*: time gained and distance left to give it back) and
  **`physics.number_of_tyres_out`** (a live count) drop the sector while the off-track is under way,
  where the game publishes them. While the lap is valid "enough" is all four tyres (the game's own
  rule); once the lap is invalid a lower count (Settings: *...once the lap is invalid*, default 2)
  applies for the rest of that lap.

These signals overlap: the same cut can be seen live by the race-cut pair or the lap flag and again in
the log. Each invalidation is recorded against a `(lap, sector)`, so the first signal to reach a sector
acts and the others are folded into it — one cut drops one sector and is announced once — while two
cuts in different sectors of the same lap each drop their own.

**Why a report may still be read back.** The game judges a cut by the time it gains: it gives the
driver a window to give that time back, and only reports the cut once the window has passed. On-track
data (Monza) shows the report naming the corner it happened in - a cut in the Ascari chicane comes
back around the corner's exit - so the position in the report is used as it is (`cut_give_back_m`
defaults to `0`). A non-zero window still reads the report that far back along the lap, for data that
expects it. If the sector a cut lands in was already saved, its run is taken back
(`S3 had its stored run taken back`); if it is still in progress, the sector is marked as not counting
(`S3 won't count · off track`).

**Read from the line's own time.** The game buffers this log (a few KB, flushed when full), so a line
can reach the file a minute after it was written - or after the lap it belongs to has ended - and one
read can bring a whole lap's cuts at once. Every line carries its own timestamp, so the app attributes
each cut from the car's position *at that time* — not from wherever the car is when the line is
finally read. The sampled history it looks that up in records the lap too, so a cut is dropped in the
lap it happened in and never in the sector of the same number in the lap being driven now. When its
lap is over the colours for it are gone from the sector bar, so the status line names it instead
("S3 of the last lap won't count · cut"). The debug log shows the read lag and the lap per cut
(`... written at ... (read 12.3 s later, 1 lap back), car at 49.7% (S3) ...`).

The old tyre-count log format (`Limits: car ... tyres out changed`) is still recognised for older
builds, with the player's car taken from the log's connection lines. An infraction the game judges
from something it does not expose (no cut in its log, no race cut and no tyres reported off) cannot
be pinned to a sector. With the log being read, every cut is in it, so the app stays quiet and notes
the fallback only in its debug log; with the log switched off it warns, and can only drop the sector
where the flag dropped.

## Behaviours worth knowing

- **Idle timeout.** The SDK stops capturing after 120 s of standing still before the first lap
  (sitting in the pits, waiting in an online lobby). The app disables that timeout.
- **Watchdog.** If capture stops for any other reason, the app logs
  `Telemetry stopped (<reason>); restarting`, waits two seconds and starts a new capture. The
  sector in progress is discarded so a gap cannot produce a wrong sector time.
- **Rate.** 60 Hz by default (5-60 in Settings). Sector times are accurate to better than one sample:
  a line crossing is interpolated between the two frames around it rather than snapped to one. The
  residual is mostly the game log's millisecond timestamp resolution, a few cm at racing speed, plus
  the sample interval at low rates, so "well under one telemetry frame" is the useful bound. A
  higher rate smooths live data but the line is never snapped to it; reading faster than the game
  updates shared memory also adds duplicate frames rather than new information.
- **Game exit.** While waiting for the game, the app runs `tasklist` every 3 seconds and looks for a
  process whose name contains `assettocorsaevo` (case-insensitive). Once it finds the game it opens a
  Windows handle to that process and checks it every poll, so the exit is noticed within a fraction of
  a second and the app closes straight away (after saving). If Windows will not give the app a handle
  (for example because of anti-cheat protection), it falls back to running `tasklist` every second and
  closes after two checks without the game, about 2 seconds. If `tasklist` cannot be run, the app
  never closes itself.

## Caveats

- The game is in Early Access and the SDK is alpha: fields can change between updates. All SDK
  access is in `telemetry.py` and all log parsing in `gamelog.py`, so a change should only touch
  those files.
- The game does not always publish the live tyre count: in testing `number_of_tyres_out` stayed 0
  while the game invalidated laps, and the race-cut pair was never filled in either. The game's log
  is what reports each cut; the other two are kept as fallbacks for a build that does publish them.
  If sectors stop counting unexpectedly, turn on verbose logging and check the log, and turn the
  tyre checks off in Settings.
- If the app cannot find the game log it says so and falls back to the lap flag alone (one cut per
  lap). Point it at the right folder in Settings: *Game log folder*.
- Whether telemetry readers are acceptable in online sessions is the game's and server's call;
  check the game's terms and anti-cheat policy before using any tool online.
