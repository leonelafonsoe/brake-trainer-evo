# Troubleshooting

## Installing and running

**`Activate.ps1 cannot be loaded because running scripts is disabled`**
PowerShell's execution policy blocks the virtual-environment script. Either allow scripts for your
user once, or skip activation:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
# or, without activating:
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m brake_trainer
```

**`pip` is not recognized**
Python is not on your PATH. Use the launcher instead: `py -m pip install -e ".[dev]"`. If `py` does
not exist either, install Python 3.10+ from python.org (tick "Add python.exe to PATH") or run
`winget install Python.Python.3.12`, then open a new terminal. If typing `python` opens the
Microsoft Store, Python is not really installed.

**Windows SmartScreen or antivirus flags the executable**
Unsigned executables built with PyInstaller are sometimes flagged. Prefer the folder build
(`py scripts/build_exe.py`), or build it yourself from the source, which is the safest option.
For SmartScreen use "More info -> Run anyway" only for a build you made yourself.

**The built .exe shows the wrong (default) icon**
Explorer caches the icon of a file by its path, so a new build over the same path (`dist\BrakeTrainerEvo\BrakeTrainerEvo.exe`) can keep showing the
old icon even though the new one is inside. The app itself (taskbar, window, tray) draws its icon in
code and is not affected. To check and refresh:

1. Look at the start of the build output for `Using icon: ...\packaging\icon.ico`. If it says "no icon
   found", the file `packaging\icon.ico` is missing (regenerate it with `py scripts/make_icon.py`).
2. Copy the `.exe` to another folder or rename it. A new path has no cached icon, so you see the real one.
3. Refresh the cache:

   ```powershell
   ie4uinit.exe -show
   # if that is not enough:
   taskkill /f /im explorer.exe
   del "$env:LOCALAPPDATA\IconCache.db" -ErrorAction SilentlyContinue
   del "$env:LOCALAPPDATA\Microsoft\Windows\Explorer\iconcache_*.db" -ErrorAction SilentlyContinue
   start explorer.exe
   ```

A `.exe` built before version 0.3.8 has no icon at all; rebuild it.

## The overlay

**The overlay does not appear over the game**
It cannot draw over *exclusive fullscreen*. Set the game's display mode to borderless / windowed
and leave "Always on top" enabled. Sound cues work in every mode.

**I cannot click the overlay any more**
"Click-through" is on. Use the tray icon -> "Overlay click-through" to turn it off, or open the
settings from the tray.

**The overlay is off-screen or in the wrong place**
Right-click it (or the tray icon) -> "Reset position". It returns to the top centre of the main
screen.

**The text is hard to read on a bright background**
Raise "Background opacity" in Settings -> Overlay, or lower the game's brightness at the top of
the screen. The text has a soft shadow, but a fully transparent window cannot guarantee contrast.

## Sound

**No beeps**
Check Settings -> Cues: "Sound cues" on, volume above 0, and use the "Test" buttons. The beeps
play through the default Windows audio device. Also check that learning has produced braking points
at all: the status line shows "No braking points yet" until it has.

**Beeps come too early or too late**
Change "Warning lead time" (default 1.6 s). Beeps are position-based, so a different line, a
different car setup or a heavy fuel load moves your real braking point.

## Learning

The line under the sector bar usually tells you why nothing is being learned:

| Status line | Meaning | What to do |
| --- | --- | --- |
| Warm-up lap · not learning | The first lap after the pits (and after starting the app) is skipped | Keep driving, or set "Ignore laps after leaving the pits" to Off |
| Waiting for the game's sector lines | A new track that no car has learned the lines on: the app is waiting for the game's log to report its sector splits, and counts nothing meanwhile | Drive a lap; if it lasts more than three laps see the entry above |
| Learning paused | Learning is off | Press the resume button on the overlay |
| S3 won't count · lap invalidated | The game invalidated the lap for a cut in that sector | Nothing; the next clean sector counts |
| S3 won't count · off track | The game reported a cut in that sector | If it triggers too often set "Skip sector if tyres off track" and "...once the lap is invalid" to Off |
| No braking points yet | Nothing learned for this track and car | Drive 2-3 clean laps after the warm-up lap |

An out-lap is one of the warm-up laps above: the game invalidates the lap it began in (a lap started
in the pits gets no green flag), but that sector was going to be skipped as a warm-up anyway, so the
app does not announce it - the reason is kept on that sector's own result ("S1 not counted · warm-up
lap"). "The game invalidated the lap at ..." is only said when a sector that would otherwise have
counted is being taken out. Cut reports are skipped the same way for a sector that already will not
count (a warm-up lap, the lines being found, or one already reported as not counted): its result
keeps the reason.

**A second off-track moment in the same lap is not dropped**
Once the game has invalidated a lap its "lap valid" flag stays down, so it cannot show a later
mistake. The per-cut event the game writes to its log is what catches those, and the app follows
that log (Settings -> App -> *Follow the game's log*). If the log cannot be found the app
says so and only the lap flag is left. If a later sector is still saved after a moment the game
flagged, turn on verbose logging and share the log: it records every track-limit signal with its
position, sector and the sector the cut was attributed to. See
[TELEMETRY.md](TELEMETRY.md#track-limits).

**A cut is dropped one sector too late (or too early)**
The game reports a cut around the corner it happened in, so the position in the report is used as it
is and no setting is needed (the stored `cut_give_back_m` is `0` by default). If your build reports cuts from
further back, the stored config value `cut_give_back_m` can be set to read a report that far back
(larger reads further back; `0` uses the sector the report arrives in). The verbose log prints, per
cut, the car's position when the report was written, the position attributed and the sector of each,
so the right value can be read off a single run.

The game buffers its log (a few KB, flushed when full), so a cut can be read a minute after it was
written - or after the lap it was in has ended - and a whole lap's cuts can arrive at once. The app
attributes each one from the time on its line, not from when it was read, and from the lap that time
falls in, so a late read neither pushes a cut into the next sector nor greys a sector of the lap you
are driving now. A cut whose lap is already over has nowhere left on the sector bar, so the status
line names it ("S3 of the last lap won't count · cut") and the run that lap saved is taken back. That
is why a sector can be scored (green) from the car's own telemetry and only turn grey later, when the
game finally writes the line: the app has no reason to doubt the sector until the game says otherwise,
and it is the game's buffer, not the app, that holds the news back.

**Corners are missing or doubled**
Braking points closer than "Same-corner distance" (40 m) count as one corner. Tune it in Settings
-> Detection. Light braking never counts: raise or lower "Minimum peak pressure" and "Minimum
speed shed" to match your pedal and driving style.

**A corner sits in the middle of a sector (a sector line cuts a chicane)**
The app uses the game's own sector lines, so this should not happen: the game puts them at corner
exits. If it does, the entry is using equal splits - because its lines were never learned (data from
before 0.3.11, the game log not followed, or a build that writes no splits). The quiet line under the
sector bar says "equal sector lines", and Settings -> Data shows "equal splits". Delete *every* entry
on that track and drive a lap with *Follow the game's log* on: the lines are learned from the
game's splits. Deleting only one entry is not enough - a new entry takes the lines from any other car's
file on the same track (they are the track's lines, not the car's).

**The overlay says "Waiting for the game's sector lines" and no sector is timed**
That is the first lap or so on a track whose lines no car has learned yet: the app is waiting for the
game's log to report its sector splits, and it counts nothing live meanwhile so that no run is filed
under lines that then move. Sectors that close in the meantime are timed from the samples once the
lines arrive, so that lap is not lost unless it was a warm-up lap or the game took a sector out. A car
arriving at a track another car has already driven starts counting straight away - the lines are the
track's. If it lasts more than three laps, the app settles for equal splits and says so (the laps
driven meanwhile are timed on them then) - check *Follow the game's log* and *Game log folder*
in Settings -> App.

**The sector lines look slightly early or late**
The app places each line at the car's position when the game's own split was written, interpolated
between the telemetry frames either side; it should be well under a metre out at 60 Hz. To check it
on track, turn on verbose logging and look for `splits: audit ...` lines: each later split compares
the learned line with the game's (`the app's line was crossed 2.1 ms / 0.1 m after the game's`).
`after` means it is slightly further round the lap, `before` slightly short. A value that stays at
metres is worth reporting: share the app log and the matching game log. The game log on its own has
the split times but not the car's position, so it cannot show where a line was placed.

**"not counted · the lines were learned mid-sector"**
A new track and car starts on stand-in equal splits, because the game's own lines can only be read from
its log (no other part of the game exposes them). The log is buffered, so the read that brings them can
land with a sector already part-way through: that sector was being timed from a stand-in line, which
sits somewhere else than the game's. Normally the samples still say when the car crossed the game's
line, so the sector is moved onto it and counts; this note is what remains when that crossing is gone
(a reset, or a pause longer than the half-hour of samples the app keeps). The sector you were in when
the lines were learned, and the ones that closed before, are both recovered this way; where you braked
in them is used either way, so the first cues appear straight away even before a sector has been
scored. Those stand-in points count as one run each, so once a couple of laps have been timed they are
out-voted by your own runs and stop mattering.

**The marks look wrong after changing car setup, tyres or conditions**
Delete that entry in Settings -> Data and relearn. Your fastest 3 runs per sector stay until
something faster replaces them, even if they were set in different conditions.

**Telemetry stopped / no data**
The log shows `Telemetry stopped (<reason>); restarting`. The app restarts capture by itself. If
it keeps happening, send the log lines around it in an issue. The game must be running and in a
session; menus and loading screens are ignored.

## The app does not close with the game

The app looks for a process whose name contains `assettocorsaevo`. Normally it closes within a
second of the game exiting (about 2 seconds if it could not open a handle to the game process). Open Task Manager while the game
runs, find its process name, and put a distinctive part of it in Settings -> App -> "Game process
name contains". "Close when the game exits" must also be on.

## Logs and resetting

The app always writes a rotating log (about 1 MB per file, 3 older ones kept):

`%APPDATA%\BrakeTrainerEvo\brake_trainer.log`

Settings -> Diagnostics -> **Open app log folder** opens it. **Verbose (debug) logging** adds a line
every time the game's track-limit signals change (the race-cut pair and the live tyre count, where the
game publishes them, the lap flag and the timing invalid flag) and each time the app reads a cut from
the game's log, with the position, the sector it was reported in and the sector the cut was attributed
to. It also records which telemetry regions the SDK attached to. That is the detail a report about a
kept or dropped sector needs, so the fastest way to report a track-limits problem is:

1. Turn on "Verbose (debug) logging" (Settings -> Diagnostics), apply, and reproduce the problem
   for a lap or two.
2. Open the log folder and share the `brake_trainer.log` file.

Verbose logging can also be forced for a single run, before the app starts, without changing a
setting: pass `--debug` on the command line, or set the environment variable `BRAKE_TRAINER_DEBUG=1`.
It takes effect immediately when you toggle the setting, no restart needed. It is off by default,
so the log stays small in normal use.

- Reset settings: delete `%APPDATA%\BrakeTrainerEvo\settings.json`
- Reset learned data: Settings -> Data, or delete the files in `%APPDATA%\BrakeTrainerEvo\data\`
- The game's own log, which the app reads for cuts, lives in `Saved Games\ACE\Logs` (**Open the
  game's log folder** in Diagnostics, or set the path under Settings -> App -> *Game log folder*).

See [DATA.md](DATA.md) for what the files contain.
