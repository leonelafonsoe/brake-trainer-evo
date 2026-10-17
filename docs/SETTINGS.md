# Settings reference

*Generated from the settings window by `scripts/gen_settings_doc.py`. Do not edit by hand.*

Open the settings window from the overlay (hover, then the gear), the overlay's right-click menu,
or the tray icon. **Apply** saves and takes effect immediately. Settings are stored in
`%APPDATA%\BrakeTrainerEvo\settings.json`; the "Key" column is the name used in that file.


## Cues

| Setting | Key | Default | Range | What it does |
| --- | --- | --- | --- | --- |
| Sound cues | `sound_enabled` | on | on / off | Turn all cue sounds on or off. The overlay keeps working. |
| Volume | `volume` | 0.6 | 0 - 1 | Loudness of the beeps, from 0 (silent) to 1. |
| Warning lead time | `lead_s` | 1.6 s | 0.3 - 5 s | The low beep sounds this many seconds before the braking point. |
| Minimum warning distance | `min_lead_m` | 35 m | 5 - 300 m | At low speed the warning never comes closer than this. |
| 'Brake now' window | `here_m` | 8 m | 2 - 50 m | The high beep sounds when you are this close to the point. |
| Skip cue if brake above | `skip_zone_if_braking` | 0.1 | 0 - 1 | No beep if you are already braking harder than this. |
| Warning tone | `warn_hz` | 900 Hz | 200 - 4000 Hz | Pitch of the low warning beep (braking point coming up). |
| Warning length | `warn_ms` | 90 ms | 30 - 500 ms | Length of the warning beep. |
| Brake-now tone | `here_hz` | 1800 Hz | 200 - 4000 Hz | Pitch of the high beep (you are at the braking point). |
| Brake-now length | `here_ms` | 120 ms | 30 - 500 ms | Length of the high beep. |

## Detection

| Setting | Key | Default | Range | What it does |
| --- | --- | --- | --- | --- |
| Braking starts above | `brake_on` | 0.25 | 0.05 - 0.95 | Pedal position that counts as the start of a braking event. |
| Braking ends below | `brake_off` | 0.1 | 0.01 - 0.9 | Pedal position below which a braking event ends. |
| Minimum peak pressure | `min_peak` | 0.4 | 0.1 - 1 | Light brake touches below this peak are ignored. |
| Minimum speed shed | `min_speed_drop` | 15 km/h | 1 - 100 km/h | A braking event must slow the car by at least this much. |
| Same-corner distance | `cluster_m` | 40 m | 5 - 200 m | Braking starts closer than this are treated as the same corner. |

## Sectors

| Setting | Key | Default | Range | What it does |
| --- | --- | --- | --- | --- |
| Learn braking points | `learning_enabled` | on | on / off | Off = cues still play, but nothing is saved or changed (e.g. during a race). |
| Sectors per lap | `n_sectors` | auto | auto, or 1 - 24 | 0 = automatic from the track length. |
| Automatic: sector length | `sector_length_m` | 1000 m | 200 - 5000 m | Automatic mode: aim for about one sector per this distance. |
| Automatic: minimum sectors | `min_sectors` | 3 | 1 - 24 | Automatic mode: never use fewer sectors than this. |
| Automatic: maximum sectors | `max_sectors` | 8 | 1 - 24 | Automatic mode: never use more sectors than this. |
| Place sector lines on straights | `snap_sector_boundaries` | on | on / off | Surveyed on the warm-up lap, so a corner is never split between two sectors. |
| Ignore laps after leaving the pits | `warmup_laps` | 1 | off (0), or 1 - 5 | Cold tyres and brakes make you brake earlier, so these laps are not learned. |
| Skip sector if lap invalidated | `skip_invalid_sectors` | on | on / off | A sector where the game invalidates your lap (track limits, cuts) is not saved. |
| Skip sector if tyres off track | `max_tyres_out` | 4 | off (0), or 1 - 4 | The game's live count of tyres off the track, where it publishes it. A sector is not saved if this many were off at any moment, also twice in the same lap. Off leaves it to the game's race cut and the lap flag. |
| ...once the lap is invalid | `max_tyres_out_after_invalid` | 2 | off (0), or 1 - 4 | The game's lap flag only drops once, so the race cut and the tyre count carry the later mistakes. For the rest of an invalidated lap a sector is not saved if this many tyres go off the track in it. |
| Cut give-back window | `cut_give_back_m` | 500 m | 0 - 2000 m | The game judges a cut by the time it gains and reports it only after you have failed to give that time back within this distance, so the sector it happened in is this far behind the report. 500 m is the game's own window; 0 uses the position the report arrives at. |
| Fastest runs kept per sector | `top_runs` | 3 | 1 - 10 | Cue points are the median of these runs. 1 = copy your single best run. |
| Own runs before leaving reference | `own_runs_to_replace_ref` | 2 | 1 - 10 | With a new car, borrowed points are used until you have this many runs. |
| Preferred reference car | `reference_car` | empty | text | Part of a car name. Empty = the car with the most data on that track. |

## Overlay

| Setting | Key | Default | Range | What it does |
| --- | --- | --- | --- | --- |
| Always on top | `overlay_always_on_top` | on | on / off | Needs the game in borderless / windowed mode to be visible over it. |
| Opacity | `overlay_opacity` | 1 | 0.3 - 1 | Opacity of the whole overlay, text included. |
| Background opacity | `overlay_background` | 0 | 0 - 0.9 | 0 = fully transparent (HUD style). Raise it if the text is hard to read. |
| Click-through | `overlay_click_through` | off | on / off | Mouse clicks pass through to the game. Use the tray icon to switch it off. |

## App

| Setting | Key | Default | Range | What it does |
| --- | --- | --- | --- | --- |
| Close when the game exits | `close_with_game` | on | on / off | Quit automatically (after saving) when the game exits. |
| Game process name contains | `game_process` | assettocorsaevo | text | Part of the game's process name, used to detect that it is running or has closed. |
| Follow the game's log for cuts | `use_game_log` | on | on / off | The game's shared memory can only show the first cut of a lap (its "lap valid" flag drops once). The game's log records one event per cut, which the app uses to drop a second cut's sector too. |
| Game log folder | `game_log_dir` | empty | text | Where the game writes its logs. Empty = the usual place under Saved Games (<profile>/Saved Games/ACE/Logs). |
| Telemetry rate | `telemetry_hz` | 60 Hz | 5 - 60 Hz | How often telemetry is read. Higher is more precise; 60 is plenty. |

## Diagnostics

| Setting | Key | Default | Range | What it does |
| --- | --- | --- | --- | --- |
| Verbose (debug) logging | `debug_logging` | off | on / off | Write extra detail to the log, including the game's track-limit signals (the race cut and the live tyre count) and the lap flag at every change. Turn it on, reproduce a problem, then share the log file. |

## Stored but not shown in the window

- `overlay_x` (default auto)
- `overlay_y` (default auto)

The overlay position is saved when you drag the window. "Reset position" in the overlay or tray menu moves it back to the top centre.
