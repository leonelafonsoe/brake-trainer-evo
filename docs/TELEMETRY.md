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
| Tyres off track | `physics.number_of_tyres_out` | Skipping sectors with all four tyres out (backup for the log) |
| Track-limit violations | the game's log (see below) | Skipping every sector with a violation |
| Timestamp | frame timestamp | Sector times |

**Position source.** The SDK also returns a position estimated from the physics data
(`normalized_position_source: physics_tyre_z`). That one is dead-reckoned and can jump, so the app
uses the game's own value from the graphics block. Frames without a track or car name (menus,
loading) are ignored.

## The game's log (track limits)

Shared memory only gives the *number* of tyres off the track. The game itself decides on track limits
from a distance as well, and it writes each change to its log. Following the analysis behind
`acevo-sdk` (which parsed real logs), a violation that invalidates a lap is: **all four tyres out, at
least 2 m beyond the line**; shorter excursions are tolerated, and a very large distance (over about
10 m) is an artefact of being teleported to the pits. The app follows the newest `*.txt` in
`Saved Games\ACE\Logs` (a different folder can be set in Settings) and reads lines like:

```
[physics] [info] Limits: car <uuid> tyres out changed: 3 -> 4 with 2.62m inside
```

The player's car is recognised from the `... connected on car ..., with new carId <uuid>` line (the one
with a Steam id). Everything already in the log when the app starts, or when the game starts a new
log, is read only to learn the player's car, so old violations are never replayed. A violation makes
the sector in progress not count, and a sector that closed in the last second is taken back (the log
can arrive a moment late). This is the game's own "off limits" and is independent of the lap flag,
so a second violation in a later sector of the same lap is caught too.

The log format and folder come from the SDK's research on the alpha game; if they change this
signal stops working silently, and the other checks (below and the game's lap flag) still apply.

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
