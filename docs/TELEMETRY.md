# Telemetry notes

How the app gets its data from Assetto Corsa EVO, and the quirks to know about.

The game publishes telemetry through shared memory. The app reads it with
[`acevo-sdk`](https://github.com/glebulon/acevo-sdk) (MIT licensed, early alpha). It only reads;
it never writes to the game or its files.

## Fields used

| Value | SDK source | Used for |
| --- | --- | --- |
| Track position (0..1) | `graphics.normalized_car_position` | Where you are on the lap |
| Brake pedal (0..1) | `physics.brake` | Braking events |
| Speed | `physics.speed_kmh` | Braking events, cue timing |
| Track / car name | `static.track`, `graphics.car_model` | Keys for the stored data |
| Track length | `static.track_length_m`, or `graphics.lap_length_km` | Metres from positions |
| In the pit lane | `graphics.is_in_pit_lane` | Not learning in the pits; warm-up reset |
| Lap still valid | `graphics.is_valid_lap` | Skipping the sector where the lap was invalidated |
| Race cut (off-track) | `graphics.race_cut_gained_time_ms`, `graphics.distance_to_deadline` (raw graphics block) | Skipping the sector where an off-track happened |
| Tyres off track | `physics.number_of_tyres_out` | Skipping any sector with enough tyres off |
| Timestamp | frame timestamp | Sector times |

**Position source.** The SDK also returns a position estimated from the physics data
(`normalized_position_source: physics_tyre_z`). That one is dead-reckoned and can jump, so the app
uses the game's own value from the graphics block. Frames without a track or car name (menus,
loading) are ignored.

## Track limits

Track limits come from the game's telemetry; its log is not read. Three of the game's own signals are
used:

- **`graphics.race_cut_*`** — the *race-cut pair* the game fills in every time a wheel goes off the
  track: the time it judged the driver gained (`race_cut_gained_time_ms`) and the distance left to
  give it back (`distance_to_deadline`). A new cut is the pair coming up, or the gained time changing
  to another value. It is a **per-excursion** signal, so it drops the sector each off-track happened
  in — including a second one in a lap the game has already invalidated. The SDK decodes the graphics
  region but does not surface these three fields, so they are read from the raw block at the offsets
  its offset table already defines (all in `telemetry.py`).
- **`graphics.is_valid_lap`** is the game's verdict on the lap. It is a *state*: it drops when the
  game invalidates the lap and stays down until the lap ends, so on its own it marks only the sector
  where it dropped.
- **`physics.number_of_tyres_out`** is a *live count* of tyres off the track, where the game
  publishes it. It is checked on every sample, with the same effect as the race cut. While the lap is
  valid "enough" is all four tyres (the game's own rule); once the lap is invalid a lower count
  (Settings: "...once the lap is invalid", default 2) applies for the rest of that lap.

The game's own rule is all four tyres out *and* a distance beyond the line, and it also invalidates
for cuts judged from the car's position. An infraction the game judges from something it does not
expose per violation cannot be pinned to a sector: when the lap flag drops with no race cut and no
tyres reported off, the app logs a warning and can only drop the sector where the flag dropped.

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
  access is in `telemetry.py`, so a change should only touch that file.
- The game does not always publish the live tyre count: in testing `number_of_tyres_out` stayed 0
  while the game invalidated laps. The race-cut pair is the signal that fires; the tyre count is kept
  as a fallback where a build does publish it. If sectors stop counting unexpectedly, turn on verbose
  logging and check the log, and turn the tyre checks off in Settings.
- Whether telemetry readers are acceptable in online sessions is the game's and server's call;
  check the game's terms and anti-cheat policy before using any tool online.
