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
| Cuts reported after the fact | newest file in `Saved Games\ACE\Logs` | Skipping the sector each cut happened in |
| Timestamp | frame timestamp | Sector times |

**Position source.** The SDK also returns a position estimated from the physics data
(`normalized_position_source: physics_tyre_z`). That one is dead-reckoned and can jump, so the app
uses the game's own value from the graphics block. Frames without a track or car name (menus,
loading) are ignored.

## Track limits

Track limits follow the game, using three of its own signals:

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

**Why a report is read back.** The game judges a cut by the time it gains: it gives the driver a
fixed window (500 m, its own rule) to give that time back, and only reports the cut once the window
has passed. By then the car has driven on, so the sector the cut is really about is the one the
give-back distance behind the report (Settings: *Cut give-back window*, default 500 m). If that
sector was already saved, its run is taken back (`S3: its stored run was taken back`); if it is still
in progress, the pass is flagged (`S3 won't count`).

The old tyre-count log format (`Limits: car ... tyres out changed`) is still recognised for older
builds, with the player's car taken from the log's connection lines. An infraction the game judges
from something it does not expose (no cut in its log, no race cut and no tyres reported off) cannot
be pinned to a sector: when the lap flag drops with no other signal, the app logs a warning and can
only drop the sector where the flag dropped.

## Behaviours worth knowing

- **Idle timeout.** The SDK stops capturing after 120 s of standing still before the first lap
  (sitting in the pits, waiting in an online lobby). The app disables that timeout.
- **Watchdog.** If capture stops for any other reason, the app logs
  `Telemetry stopped (<reason>); restarting`, waits two seconds and starts a new capture. The
  sector in progress is discarded so a gap cannot produce a wrong sector time.
- **Rate.** 60 Hz by default (5-60 in Settings). Sector times are accurate to about one sample.
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
