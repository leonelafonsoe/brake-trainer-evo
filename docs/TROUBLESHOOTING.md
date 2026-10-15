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
| Learning paused | Learning is off | Press the resume button on the overlay |
| S3 won't count · lap invalidated | The game invalidated the lap in that sector | Nothing; the next clean sector counts |
| S3 won't count · off track | All four tyres were off the track | If it triggers too often set "Skip sector if tyres off track" to Off |
| No braking points yet | Nothing learned for this track and car | Drive 2-3 clean laps after the warm-up lap |

**Off-limits sectors are still saved (the game log is not read)**
The app looks for the game's log in `%USERPROFILE%\Saved Games\ACE\Logs`. The app log
(`brake_trainer.log`) says `Reading the game log: <file>` when it works, `Game log: track-limit
violation` for each violation it sees, or `No game log found in ...` when the folder is wrong. In that
case set "Game log folder" in Settings -> Sectors and restart the app. If the folder is right but nothing
is reported after a violation, open the newest log and search for `Limits: car`; if those lines look
different from `tyres out changed: 3 -> 4 with 2.62m inside`, open an issue with a few of them.

**Corners are missing or doubled**
Braking points closer than "Same-corner distance" (40 m) count as one corner. Tune it in Settings
-> Detection. Light braking never counts: raise or lower "Minimum peak pressure" and "Minimum
speed shed" to match your pedal and driving style.

**A corner sits in the middle of a sector (a sector line cuts a chicane)**
That entry was probably learned by a version before 0.3.5 (or with "Place sector lines on
straights" off), so it still uses equal splits. The quiet line under the sector bar says "equal sector
lines", and Settings -> Data shows "equal splits". Delete the entry, drive a warm-up lap, and the lines
are placed on the straights. Entries of *other cars* on the same track no longer block this.

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

- Log: `%APPDATA%\BrakeTrainerEvo\brake_trainer.log`
- Reset settings: delete `%APPDATA%\BrakeTrainerEvo\settings.json`
- Reset learned data: Settings -> Data, or delete the files in `%APPDATA%\BrakeTrainerEvo\data\`

See [DATA.md](DATA.md) for what the files contain.
