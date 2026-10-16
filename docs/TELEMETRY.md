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
| Tyres off track | `physics.number_of_tyres_out` | Skipping any sector with enough tyres off |
| Timestamp | frame timestamp | Sector times |

**Position source.** The SDK also returns a position estimated from the physics data
(`normalized_position_source: physics_tyre_z`). That one is dead-reckoned and can jump, so the app
uses the game's own value from the graphics block. Frames without a track or car name (menus,
loading) are ignored.

## Track limits

Both track-limit signals come from shared memory; the game's log is not read.

- **`graphics.is_valid_lap`** is the game's own verdict. It is a *state*: it drops when the game
  invalidates the lap and stays down until the lap ends, so it marks the sector where it dropped
  and nothing after it.
- **`physics.number_of_tyres_out`** is a *live count* of tyres off the track. It is checked on
  every sample, so a sector where enough tyres are off is dropped even when the lap was already
  invalidated: a second mistake in a later sector is caught, which the one-shot flag cannot show.
  While the lap is valid "enough" is all four tyres (the game's own rule); once the lap is invalid a
  lower count (Settings: "...once the lap is invalid", default 2) applies for the rest of that lap,
  because the flag stays down and the four-tyre spike can be easy to miss.

The memory has **no distance beyond the line and no per-violation event**. The game's own rule is
all four tyres out *and* a distance beyond the line, and it also invalidates for cuts, which are
judged from the car's position rather than the tyre count. A cut is therefore invisible to the app:
when the lap flag drops but the memory never reported four tyres off, the app logs a warning and can
only drop the sector where the flag dropped.

The cut warning doubles as a check on the tyre signal: if `number_of_tyres_out` ever stopped being
reported (a game or SDK change), every lap invalidation would look like a cut and the warning would
appear in the log each time.

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
- I have not verified how the game counts `number_of_tyres_out` on kerbs. If sectors stop
  counting unexpectedly, set "Skip sector if tyres off track" to Off.
- Whether telemetry readers are acceptable in online sessions is the game's and server's call;
  check the game's terms and anti-cheat policy before using any tool online.
