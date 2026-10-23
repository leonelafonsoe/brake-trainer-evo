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
| Ignore laps after leaving the pits | `warmup_laps` | 1 | off (0), or 1 - 5 | Cold tyres and brakes make you brake earlier, so these laps are not learned. The first laps of a new track are ignored too, while the game's sector lines are being learned from its log. |
| Skip sector if lap invalidated | `skip_invalid_sectors` | on | on / off | A sector where the game invalidates your lap (track limits, cuts) is not saved. |
| Skip sector if tyres off track | `max_tyres_out` | 4 | off (0), or 1 - 4 | The game's live count of tyres off the track, where it publishes it. A sector is not saved if this many were off at any moment, also twice in the same lap. Off leaves it to the game's race cut and the lap flag. |
| ...once the lap is invalid | `max_tyres_out_after_invalid` | 2 | off (0), or 1 - 4 | The game's lap flag only drops once, so the race cut and the tyre count carry the later mistakes. For the rest of an invalidated lap a sector is not saved if this many tyres go off the track in it. |
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
| Follow the game's log | `use_game_log` | on | on / off | Read the game's log for the cuts it reports and the sector splits that mark its own lines. Shared memory only shows the first cut of a lap (its "lap valid" flag drops once); the log records one event per cut and every sector split. |
| Game log folder | `game_log_dir` | empty | text | Where the game writes its logs. Empty = the usual place under Saved Games (<profile>/Saved Games/ACE/Logs). |
| Telemetry rate | `telemetry_hz` | 60 Hz | 5 - 60 Hz | How often telemetry is read. Higher makes live data a little smoother; 60 is plenty. Sector lines are interpolated between samples rather than snapped to them, so it can refine the estimate only up to the rate the game publishes. |

## Diagnostics

| Setting | Key | Default | Range | What it does |
| --- | --- | --- | --- | --- |
| Verbose (debug) logging | `debug_logging` | off | on / off | Write extra detail to the log, including the game's track-limit signals (the race cut and the live tyre count) and the lap flag at every change. Turn it on, reproduce a problem, then share the log file. |

## Stored but not shown in the window

- `cut_give_back_m` (default 500)
- `overlay_x` (default auto)
- `overlay_y` (default auto)

The overlay position is saved when you drag the window. "Reset position" in the overlay or tray menu moves it back to the top centre.
