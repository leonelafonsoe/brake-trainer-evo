# Guide

What Brake Trainer EVO does while you drive, and what to do when it does not. For *why* it works
this way, see [DESIGN.md](DESIGN.md). The numbers below are the defaults; every one can be changed
in Settings (see [SETTINGS.md](SETTINGS.md)). The game data and log lines it reads, and the files it
writes, are in [GAME_DATA.md](GAME_DATA.md).

## The idea

Every time you brake hard, the app notes **where on the track the braking started**. After a few
good laps it knows your usual braking points for that track and car, and plays a beep as you
approach them. It learns your own marks, so there is nothing to configure per track.

## Words used here

- **Sector**: one of the game's three parts of a lap.
- **Line** (or **boundary**): where one sector ends and the next begins. The app learns the two
  inner lines from the game's splits.
- **Split**: the time the game reports as you cross a sector line; also the log line that carries it.
- **Pass**: the driving through one sector, from one line to the next.
- **Run**: the stored result of a counted pass - its time and where you started braking.
- **Session**: one run of the game, from connecting to closing. Stored runs survive between sessions.

## Braking events

A braking event is detected from the brake pedal and speed:

1. The pedal goes above **25%**: a possible event starts, and the track position is noted.
2. The event counts only if the pedal reaches **40%** at some point **and** the car sheds at least
   **15 km/h**. Light touches and lifts are ignored.
3. The event ends when the pedal drops 15 points below the start threshold (below **10%** with the
   default 25% start).

The position noted in step 1 is the *braking point* for that corner.

## Sectors

The lap is split into **three** sectors, the game's own. Sectors exist so the app can keep the
**best** driving and so a mistake late in the lap does not cost you the good part of it:

- Each sector is timed on its own.
- The moment you finish a sector, it is compared with your kept runs for that sector. If it is
  among your **3 fastest**, its braking points are saved straight away, even if you crash two
  corners later.
- The cue point for a corner is the **median** of the braking points in your kept runs, so one
  unusually late (or early) lap does not move it much. A corner has to appear in at least half of
  the kept runs to become a cue point.
- A lap that closes while the app is still waiting for the game's sector lines contributes its
  braking points at once, because where you brake is a place on the track and needs no sector line
  to be useful; once the lines arrive, its sectors are timed from the samples too. Warm-up laps
  contribute nothing, and a lap the game ruled out contributes only the sectors where you stayed on
  the track (see [What is not learned](#what-is-not-learned)).

### Where the sector lines are

They are the game's own. Every lap is scored in three sectors and, on a timed lap, the game writes
each split to its log as you cross the line, so the app learns the two inner lines from there: the
car's position at the moment the game wrote the split *is* the line. Splits written on an out-lap
teach them just as well - the lines belong to the track - so the app reads them all and takes
whichever pair is complete and looks like a sector line. The game puts its lines at corner exits (at
Monza, just before the Roggia and Ascari braking points), so no corner is ever cut between two
sectors, and the app's sector times are the game's own splits.

The first lap or so is spent finding them: until both lines are known no new sector is counted,
because a stored run is timed between two lines and re-filing it later would be wrong. The status
line says "Waiting for the game's sector lines" while that happens - it is the app waiting on the
game, not something you have to fix - and in the meantime the sector bar is drawn on the equal
splits as a stand-in. The sectors that close before the lines arrive are not lost: the samples still
say when the car crossed each line, so they are timed and stored the moment the lines are known
(unless the game took one out). The lines are saved with the track data, and because they are the
track's rather than the car's, every other car driven here takes them from that file the moment it
is opened: only the very first car on a track waits. Once learned they are never moved - to learn
them again, delete the entries on that track in Settings -> Data and drive a lap (leaving one behind
would just hand its lines to the new entry). If the log is not being followed, or a build does not
write splits, the app settles for equal splits after three laps and says so - and the laps driven
while waiting are timed on them at that point, since they become the lines.

The line's own timestamp is when the car crossed it. The car's position at that instant is
**interpolated between the two telemetry frames either side**, not taken from the nearest one (the
previous code took the last frame at or before the split, so every line was early): at racing speed
a frame is about a metre, so the nearest frame would leave up to half a metre of error, on either
side. Sector times close the same way, on the interpolated crossing, so a sector's duration is not
quantised to a frame.

The log is buffered by the game, so the read that brings the splits often lands well after the car
crossed the line. The sector you are in when they are read began on one of the stand-in equal lines,
which sits in a different place from the game's own; the samples still have the crossing, so the
pass is moved onto the game's line and timed from there. Only when that crossing is gone from the
samples (a reset, or a pause longer than the kept history) is the sector dropped, with "not counted
· the lines were learned mid-sector", rather than blamed on the pit lane or a reset.

**Data whose lines were never learned** - a fresh entry, or one saved by a build that did not read
the game's splits - keeps the equal splits it was learned with, so a corner can still be cut by a
line. The overlay then shows "equal sector lines" in its quiet summary, and Settings -> Data lists
it as "equal splits". Delete that entry and drive a lap to learn the game's lines.

The start/finish line never moves, so a braking zone very close to it can still wobble between the
last and the first sector.

## A typical session

| When | What happens |
| --- | --- |
| You start the app | It waits for the game. The overlay opens at the top centre of the screen under the cursor. |
| You leave the pits | **Warm-up lap**: nothing is learned (cold tyres and brakes make you brake early). The status line says "Warm-up lap · not learning". |
| You cross the line | Learning starts, once both conditions are met: the warm-up laps are over *and* the game's sector lines are known. The sectors that closed before the lines arrived are timed from the samples as soon as they are known, so the lap is not wasted; their braking points are used straight away. |
| Laps 2, 3, 4 ... | Marks accumulate. Beeps start as soon as there are saved braking points ahead of you. |
| You pit | The warm-up starts again after you leave the pits, because the tyres and brakes are different again. |
| Next session | Everything is loaded from disk. Cues work from the first lap, including the warm-up lap. |

## Cues

- **Low beep**: a braking point is coming up, about 1.6 seconds ahead (never closer than 35 m).
- **High beep**: you are at the braking point (within 8 m).
- Nothing plays if you are already braking.
- Cues use your saved marks even during warm-up laps and while learning is paused.

## What is *not* learned

A sector pass is not saved when:

- **Warm-up**: it is part of a warm-up lap.
- **Pit lane**: you were in the pit lane, or reset to the pits, during it.
- **Partial**: you reset or teleported mid-sector, or drove less than 90% of it.
- **Invalid lap**: the game invalidated your lap for a cut that happened in it (track limits). The
  game's "lap valid" flag drops once and stays down, so on its own it can only mark the first cut
  of a lap. A sector you *enter* after the lap was already invalid is kept, as long as you stay on
  the track in it (see the next point).
- **Off track**: the game reported a cut that happened while you were in that sector. This uses the
  per-cut event the game writes to its log (one per cut, and the only signal that shows a second
  cut in a lap it has already invalidated), and, where the game publishes it, the live "race cut"
  pair. The notification and the lap flag are attributed at their own position, which is where the
  game judged the cut. If that sector was already saved, its run is taken back.
  The game buffers its log, so a cut can be read a minute after it was written, or after the lap it
  belongs to has ended, and several can arrive at once. Each line carries its own time, so every cut
  still lands in the sector - and the lap - it happened in, never in the sector of the same number
  in the lap being driven now. When its lap is already over the status line says so ("S3 of the last
  lap won't count · cut"), and the run that lap had saved for that sector is taken back.
- **Paused**: learning was paused at any point during it.

While the game's sector lines are still being learned, a clean pass is held rather than dropped: it
is timed and stored on those lines as soon as they are known, or on the equal splits if the app
stops waiting, and its braking points already shape the cues. If another reason in this list also
applies (warm-up, pit, partial, invalid, off track or paused), the pass is dropped for that reason.

The signals above are the game's own. When the game invalidates a lap for an infraction it does not
expose (no cut in its log and no race cut), the app says so in its log and can only drop the sector
where the flag dropped. That warning is for the case where there is no log to read: with the game
log being followed, every cut is in it, so the app uses it instead. See
[track limits](GAME_DATA.md#track-limits).

The reason is shown on the overlay ("S3 won't count · lap invalidated") and in the log.

## Sector colours

The sector bar shows how each sector of the current lap went compared with *your own* kept runs:

| Colour | Meaning |
| --- | --- |
| Grey | Not driven yet, or not counted |
| Yellow | Slower than all your kept runs (ignored) |
| Green | Among your fastest runs, but not the fastest (it shapes your marks) |
| Purple | Your fastest run of that sector |

The first clean run of a sector is purple, because nothing is slower yet. The previous lap's
colours stay visible until you complete the first sector of the next lap. A white outline marks the
sector you are in, and fills as you drive through it. The segments are sized to the game's sectors
rather than equal thirds, and they meet exactly on the game's line, which a thin separator marks - a
gap would hide the car for a stretch around every line. On tracks with very unequal sectors (the Red
Bull Ring's first is 26% of the lap, Spa's second ends at 72%) equal blocks would put the boundary
hundreds of metres out.

The colour is a *rank*, not a stopwatch threshold: green means the run entered your `kept_runs`
fastest runs for that sector (3 by default - Settings -> Sectors). So how far off your best a
green run can be depends on how close your third-best run is; yellow means it missed the cut,
however small the gap. The result line says which, and gives the gap to the best: `S2 18.44 s ·
slower (+0.43 s)`. A new best measures itself against the run it replaced (`best (-0.13 s)`), and
the very first run of a sector has nothing to compare with. The log line carries the same number.

The colours are *not* the F1 meaning: there is no other driver to compare with, so purple is your
best and green is "good enough to count".

## The status line

The line under the sector bar shows the most relevant of these, top first:

1. A problem in the current sector (red): "S3 won't count · lap invalidated" or "off track".
2. "Learning paused" (amber).
3. "Warm-up lap · not learning", or "Waiting for the game's sector lines" on a new track, both amber.
4. The last sector result for 6 seconds, in the sector's colour: "S2 18.01 s · best (-0.42 s)".
5. "Reference: <car>" while borrowing another car's points (amber).
6. A quiet summary: "7 braking points", or "No braking points yet".

## New car on a known track

With no data of its own, a car **borrows the braking points of another car on the same track** as a
rough guide, matched by track position (so data timed between different lines still lines up). By
default it picks the car with the most data (not the fastest, which brakes latest). Once you have 2
clean runs of a sector with the new car, that sector uses your own points. The borrowed data is
never saved into the new car's file.

Braking points depend on weight, downforce, tyres and brakes, so treat borrowed points as a hint for
the first laps.

## Pausing learning

Pause learning (overlay button, tray menu, Settings, or the global hotkey) in a race so your saved
marks stay as they are. Cues keep playing and the sector colours still show how you compare. A
sector that was partly driven while paused is not saved when you resume, and held passes are not
written after you pause.

The global hotkey is **Ctrl+Alt+P** by default. Change it in Settings -> App: click the field and
press the new combination, or use its clear button to turn it off. A letter or number needs at least
one modifier (Ctrl, Alt, Shift or Win), so the app does not take that key from every other window;
F1-F12 may be used alone. If another application already owns the combination, the tray says so when
the app starts and the log records it: choose another one.

## Removing a bad time

A run you do not trust (a lucky slipstream, a run in odd conditions) can hold your marks back,
because it stays among your fastest until something quicker replaces it. In Settings -> Data you can
delete just that run, a whole sector, or the whole track and car.

## When the game closes

The app watches for the game process and closes itself (saving first) as soon as the game exits,
within a second or so. This can be switched off in Settings.

## Troubleshooting

### Installing and running

**`Activate.ps1 cannot be loaded because running scripts is disabled`**
With [uv](https://docs.astral.sh/uv/) you do not need to activate the environment:

```powershell
uv sync --extra dev
uv run python -m brake_trainer
```

If you use the venv directly, allow scripts for your user once:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

**`uv` or `python` is not recognized**
Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and Python 3.11+ from
python.org (tick "Add python.exe to PATH"), or run `winget install Python.Python.3.12`, then open a
new terminal. If typing `python` opens the Microsoft Store, Python is not really installed.

**Windows SmartScreen or antivirus flags the executable**
Unsigned executables built with PyInstaller are sometimes flagged. Prefer the folder build
(`uv run python scripts/build_exe.py`), or build it yourself from the source, which is the safest
option. For SmartScreen use "More info -> Run anyway" only for a build you made yourself.

**The built .exe shows the wrong (default) icon**
Explorer caches the icon of a file by its path, so a new build over the same path
(`dist\BrakeTrainerEvo\BrakeTrainerEvo.exe`) can keep showing the old icon even though the new one is
inside. The app itself (taskbar, window, tray) draws its icon in code and is not affected. To check
and refresh:

1. Look at the start of the build output for `Using icon: ...\packaging\icon.ico`. If it says "no
   icon found", the file `packaging\icon.ico` is missing (regenerate it with
   `uv run python scripts/make_icon.py`).
2. Copy the `.exe` to another folder or rename it. A new path has no cached icon, so you see the real
   one.
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

### The overlay

**The overlay does not appear over the game**
It cannot draw over *exclusive fullscreen*. Set the game's display mode to borderless / windowed and
leave "Always on top" enabled. Sound cues work in every mode.

**I cannot click the overlay any more**
"Click-through" is on. Use the tray icon -> "Overlay click-through" to turn it off, or open the
settings from the tray.

**The overlay is off-screen or in the wrong place**
Right-click it (or the tray icon) -> "Reset position". It returns to the top centre of the screen
under the cursor. If the monitor the HUD was on is unplugged or disabled, it moves back to the
default position by itself.

**The text is hard to read on a bright background**
Raise "Background opacity" in Settings -> Overlay, or lower the game's brightness at the top of the
screen. The text has a soft shadow, but a fully transparent window cannot guarantee contrast.

**The overlay is too small or too large**
Use Settings -> Overlay -> "HUD scale" (0.75–2.00). It scales the text, margins, bars and buttons
together; 1.00 is the normal size.

### Sound

**No beeps**
Check Settings -> Cues: volume above 0, and use the "Test" buttons. The beeps play through the
default Windows audio device. Also check that learning has produced braking points at all: the
status line shows "No braking points yet" until it has.

**Beeps come too early or too late**
Change "Warning lead time" (default 1.6 s). Beeps are position-based, so a different line, a
different car setup or a heavy fuel load moves your real braking point.

### Learning

The line under the sector bar usually tells you why nothing is being learned:

| Status line | Meaning | What to do |
| --- | --- | --- |
| Warm-up lap · not learning | The first lap after the pits (and after starting the app) is skipped | Keep driving, or set "Ignore laps after leaving the pits" to Off |
| Waiting for the game's sector lines | A new track that no car has learned the lines on: the app is waiting for the game's log to report its sector splits, and counts nothing meanwhile | Drive a lap; if it lasts more than three laps see the entry below |
| Learning paused | Learning is off | Press the pause hotkey (Ctrl+Alt+P by default) or the resume button on the overlay |
| S3 won't count · lap invalidated | The game invalidated the lap for a cut in that sector | Nothing; the next clean sector counts |
| S3 won't count · off track | The game reported a cut in that sector | Nothing; the next clean sector counts. If it looks wrong, turn on verbose logging and share the log |
| No braking points yet | Nothing learned for this track and car | Drive 2-3 clean laps after the warm-up lap |

**The pause hotkey does nothing**
Check Settings -> App -> *Global pause hotkey*. It may be empty (off), or Windows may have refused
it because another application owns that combination; the tray says so at startup and the log
records the error. Click the field, press another combination and press Apply. A letter or digit
needs a modifier; F1-F12 can be used alone.

**A second off-track moment in the same lap is not dropped**
Once the game has invalidated a lap its "lap valid" flag stays down, so it cannot show a later
mistake. The per-cut event the game writes to its log is what catches those, and the app follows
that log (Settings -> App -> *Follow the game's log*). If the log cannot be found the app says so
and only the lap flag is left. If a later sector is still saved after a moment the game flagged,
turn on verbose logging and share the log: it records every track-limit signal with its position and
sector, and every cut from the game's log with its position, lap and dropped sector. See
[track limits](GAME_DATA.md#track-limits).

**A cut is dropped in the wrong sector**
The app drops the sector where the game's notification or lap flag is written. Those events are
written where the game judged the cut: at Monza the field logs put them at natural corner exits
(Roggia 36–37%, Lesmo 50.6%, Ascari 67–68%, curve 10 71–73%), not at a fixed distance behind the
cut. If a cut still lands in the wrong sector, turn on verbose logging and share the log: it prints,
per cut, the car's position when the report was written, the lap it belongs to and the sector that
was dropped. Check that position against the sector lines in the same log before assuming the
attribution is at fault. A late read is attributed from the line's own timestamp, so it neither
pushes a cut into the next sector nor greys a sector of the lap you are driving now; see
[the buffered log](GAME_DATA.md#read-from-the-lines-own-time).

**Corners are missing or doubled**
Braking points closer than "Same-corner distance" (40 m) count as one corner. Tune it in Settings ->
Advanced, together with "Minimum peak pressure". Light braking never counts: adjust those and
"Minimum speed shed" (Detection) to match your pedal and driving style.

**A corner sits in the middle of a sector (a sector line cuts a chicane)**
The app uses the game's own sector lines, so this should not happen: the game puts them at corner
exits. If it does, the entry is using equal splits - because its lines were never learned (data
whose lines predate the game's splits, the game log not followed, or a build that writes no splits).
The quiet line under the sector bar says "equal sector lines", and Settings -> Data shows "equal
splits". Delete *every* entry on that track and drive a lap with *Follow the game's log* on: the
lines are learned from the game's splits. Deleting only one entry is not enough - a new entry takes
the lines from any other car's file on the same track (they are the track's lines, not the car's).

**The overlay says "Waiting for the game's sector lines" and no sector is timed**
That is the first lap or so on a track whose lines no car has learned yet: the app is waiting for
the game's log to report its sector splits, and it counts nothing live meanwhile so that no run is
filed under lines that then move. Sectors that close in the meantime are timed from the samples once
the lines arrive, so that lap is not lost unless it was a warm-up lap or the game took a sector out.
A car arriving at a track another car has already driven starts counting straight away - the lines
are the track's. If it lasts more than three laps, the app settles for equal splits and says so (the
laps driven meanwhile are timed on them then) - check *Follow the game's log* and *Game log folder*
in Settings -> App.

**The sector lines look slightly early or late**
The app places each line at the car's position when the game's own split was written, interpolated
between the telemetry frames either side; at 60 Hz it is usually a few tenths of a metre out, though
the residual depends on speed and on how linear the reported position is. To check it on track, turn
on verbose logging and look for `splits: audit ...` lines. A value that stays in the metres is worth
reporting: share the app log and the matching game log. See
[checking a line](GAME_DATA.md#checking-where-a-line-ended-up).

**"not counted · the lines were learned mid-sector"**
A new track and car starts on stand-in equal splits, because the game's own lines can only be read
from its log (no other part of the game exposes them). The log is buffered, so the read that brings
them can land with a sector already part-way through: that sector was being timed from a stand-in
line, which sits somewhere else than the game's. Normally the samples still say when the car crossed
the game's line, so the sector is moved onto it and counts; this note is what remains when that
crossing is gone (a reset, or a pause longer than the five minutes of samples the app keeps). The
sector you were in when the lines were learned, and the ones that closed before, are both recovered
this way; where you braked in them is used either way, so the first cues appear straight away even
before a sector has been scored. Those stand-in points count as one run each, so once a couple of
laps have been timed they are out-voted by your own runs and stop mattering.

**The marks look wrong after changing car setup, tyres or conditions**
Delete that entry in Settings -> Data and relearn. Your fastest 3 runs per sector stay until
something faster replaces them, even if they were set in different conditions.

**Telemetry stopped / no data**
The log shows `Telemetry stopped (<reason>); restarting`. The app restarts capture by itself. If it
keeps happening, send the log lines around it in an issue. The game must be running and in a
session; menus and loading screens are ignored.

**The app does not close with the game**
The app looks for a process whose name contains `assettocorsaevo`. Normally it closes within a
second of the game exiting (about 2 seconds if it could not open a handle to the game process). Open
Task Manager while the game runs, find its process name, and put a distinctive part of it in Settings
-> App -> "Game process name contains". "Close when the game exits" must also be on.

### Logs and resetting

**Settings were reset after updating**
A settings file from another layout is never migrated. 0.7.0 renamed the JSON keys and moved to
`settings_version` 5, so on first start the old file is moved to
`settings.version-4-<stamp>.json` beside `settings.json` and the app starts from defaults. Set your
tuning again once; the old file is kept as evidence and can be deleted when you no longer need it.

The app always writes a rotating log (about 1 MB per file, 3 older ones kept):

`%APPDATA%\BrakeTrainerEvo\brake_trainer.log`

Its first line names exactly what produced the log, so a report can be matched to a build without
guessing:

```text
2026-10-24 12:00:00,000 INFO    brake_trainer: startup app=0.5.0 build=2983a85ac7d3 settings_version=4 data_version=1 debug=off log=C:\Users\you\AppData\Roaming\BrakeTrainerEvo\brake_trainer.log
```

`build` is the source checkout's git revision (`-dirty` means it had uncommitted changes), the
commit baked into a packaged executable, or the value of `BRAKE_TRAINER_BUILD` when one was set.
`settings_version` and `data_version` are the settings and learned-data layouts this build reads and
writes. `debug` is the verbose state at start-up; turning the setting on afterwards adds
`Verbose (debug) logging is on (setting)`.

Settings -> Diagnostics -> **Open app log folder** opens it. **Verbose (debug) logging** adds a line
every time the game's track-limit signals change (the race-cut pair, the lap flag and the timing
invalid flag) and each time the app reads a cut from the game's log, with its position, the lap it
belongs to and the sector that was dropped. It also records which telemetry regions the SDK attached
to. That is the detail a report about a kept or dropped sector needs, so the fastest way to report a
track-limits problem is:

1. Turn on "Verbose (debug) logging" (Settings -> Diagnostics), apply, and reproduce the problem for
   a lap or two.
2. Open the log folder and share the `brake_trainer.log` file.

Verbose logging can also be forced for a single run, before the app starts, without changing a
setting: pass `--debug` on the command line, or set the environment variable `BRAKE_TRAINER_DEBUG=1`.
It takes effect immediately when you toggle the setting, no restart needed. It is off by default, so
the log stays small in normal use.

- Reset settings: delete `%APPDATA%\BrakeTrainerEvo\settings.json`
- Reset learned data: Settings -> Data, or delete the files in `%APPDATA%\BrakeTrainerEvo\data\`
- The game's own log, which the app reads for cuts, lives in `Saved Games\ACE\Logs` (**Open the
  game's log folder** in Diagnostics, or set the path under Settings -> App -> *Game log folder*).

See [GAME_DATA.md](GAME_DATA.md#files) for what the files contain.
