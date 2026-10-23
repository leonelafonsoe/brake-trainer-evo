# How it works

This page explains what Brake Trainer EVO does while you drive, in the order things happen.
For *why* it works this way, see [DESIGN.md](DESIGN.md). Every number below is a default and can
be changed in Settings (see [SETTINGS.md](SETTINGS.md)).

## The idea

Every time you brake hard, the app notes **where on the track the braking started**. After a few
good laps it knows your usual braking points for that track and car, and plays a beep as you
approach them. It learns your own marks, so there is nothing to configure per track.

## Braking events

A braking event is detected from the brake pedal and speed:

1. The pedal goes above **25%**: a possible event starts, and the track position is noted.
2. The event counts only if the pedal reaches **40%** at some point **and** the car sheds at least
   **15 km/h**. Light touches and lifts are ignored.
3. The event ends when the pedal drops below **10%**.

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
  braking points at once, because where you brake is a place on the track and needs no sector line to
  be useful; once the lines arrive, its sectors are timed from the samples too. Only warm-up laps and
  laps the game ruled out contribute nothing.

### Where the sector lines are

They are the game's own. Every lap is scored in three sectors and, on a timed lap, the game writes each
split to its log as you cross the line, so the app learns the two inner lines from there: the car's
position at the moment the game wrote the split *is* the line. (Splits written on an out-lap teach them
just as well - the lines belong to the track, and where the car was when it crossed one is the same
line - so the app reads them all and takes whichever pair is complete and looks like a sector line.)
The game puts its lines at corner exits - at Monza, just before the Roggia and Ascari braking points -
so no corner is ever cut between two sectors, and the app's sector times are the game's own splits.

The first lap or so is spent finding them: until both lines are known no new sector is counted, because
a stored run is timed between two lines and re-filing it later would be wrong. The status line says
"Waiting for the game's sector lines" while that happens - it is the app waiting on the game, not
something you have to fix - and in the meantime the sector bar is drawn on the equal splits as a
stand-in. The sectors that close before the lines arrive are not lost: the samples still say when the
car crossed each line, so they are timed and stored the moment the lines are known (unless the game took
one out). The lines are saved with the track data, and
because they are the track's rather than the car's, every other car driven here takes them from that
file the moment it is opened: only the very first car on a track waits. Once learned they are never
moved - to learn them again, delete the entries on that track in Settings -> Data and drive a lap
(leaving one behind would just hand its lines to the new entry). If the log is not being followed, or a
build does not write splits, the app settles for equal splits after three laps and says so - and the
laps driven while waiting are timed on them at that point, since they become the lines.

The line's own timestamp is when the car crossed it. The car's position at that instant is
**interpolated between the two telemetry frames either side**, not taken from the nearest one (the
previous code took the last frame at or before the split, so every line was early): at racing speed a
frame is about a metre, so the nearest frame would leave up to half a metre of error, on either side.
Sector times close the same way, on the interpolated crossing, so a sector's duration is not
quantised to a frame.

The log is buffered by the game, so the read that brings the splits often lands well after the car
crossed the line. The sector you are in when they are read began on one of the stand-in equal lines,
which sits in a different place from the game's own; the samples still have the crossing, so the pass
is moved onto the game's line and timed from there. Only when that crossing is gone from the samples (a
reset, or a pause longer than the kept history) is the sector dropped, with "not counted · the lines were
learned mid-sector", rather than blamed on the pit lane or a reset.

**Data from older versions** (before 0.3.11) keeps the equal splits it was learned with, so a corner can
still be cut by a line. The overlay then shows "equal sector lines" in its quiet summary, and
Settings -> Data lists it as "equal splits". Delete that entry and drive a lap to learn the game's
lines.

The start/finish line never moves, so a braking zone very close to it can still wobble between
the last and the first sector.

## A typical session

| When | What happens |
| --- | --- |
| You start the app | It waits for the game. The overlay opens at the top centre of the screen. |
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

- **Warm-up**: it is part of a warm-up lap, or the game's sector lines have not been learned yet (see
  above).
- **Pit lane**: you were in the pit lane, or reset to the pits, during it.
- **Partial**: you reset or teleported mid-sector, or drove less than 90% of it.
- **Invalid lap**: the game invalidated your lap for a cut that happened in it (track limits). The
  game's "lap valid" flag drops once and stays down, so on its own it can only mark the first cut of
  a lap. A sector you *enter* after the lap was already invalid is kept, as long as you stay on the
  track in it (see the next point).
- **Off track**: the game reported a cut that happened while you were in that sector. This uses the
  per-cut event the game writes to its log (one per cut, and the only signal that shows a second cut
  in a lap it has already invalidated), and, where the game publishes them, the "race cut" pair and
  the live count of tyres off the track (Settings: "Skip sector if tyres off track", and "...once the
  lap is invalid"; while the lap is still valid the tyre count takes all four tyres, the game's own
  rule). The game gives 500 m to give a cut's gained time back and reports it only after that
  window, so the app reads the report back 500 m (`cut_give_back_m`) to the sector where the cut
  happened rather than the one the report lands in. If that sector was already saved, its run is
  taken back.
  The game buffers its log, so a cut can be read a minute after it was written, or after the lap it
  belongs to has ended, and several can arrive at once. Each line carries its own time, so every cut
  still lands in the sector - and the lap - it happened in, never in the sector of the same number in
  the lap being driven now. When its lap is already over the status line says so ("S3 of the last lap
  won't count · cut"), and the run that lap had saved for that sector is taken back.
- **Paused**: learning was paused at any point during it.

The signals above are the game's own. When the game invalidates a lap for an infraction it does not
expose (no cut in its log, no race cut and no tyres reported off), the app says so in its log and can
only drop the sector where the flag dropped. That warning is for the case where there is no log to
read: with the game log being followed, every cut is in it, so the app uses it instead. See
[TELEMETRY.md](TELEMETRY.md).

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
colours stay visible until you complete the first sector of the next lap. A white outline marks
the sector you are in, and fills as you drive through it.

The colour is a *rank*, not a stopwatch threshold: green means the run entered your fastest
`top_runs` runs for that sector (3 by default - Settings -> Sectors). So how far off your best a
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

With no data of its own, a car **borrows the braking points of another car on the same track** as
a rough guide, matched by track position (so data timed between different lines still lines up). By
default it picks the car with the most data (not the fastest,
which brakes latest). Once you have 2 clean runs of a sector with the new car, that sector uses
your own points. The borrowed data is never saved into the new car's file.

Braking points depend on weight, downforce, tyres and brakes, so treat borrowed points as a
hint for the first laps.

## Pausing learning

Pause learning (overlay button, tray menu, or Settings) in a race so your saved marks stay as
they are. Cues keep playing and the sector colours still show how you compare. A sector that was
partly driven while paused is not saved when you resume.

## Removing a bad time

A run you do not trust (a lucky slipstream, a run in odd conditions) can hold your marks back,
because it stays among your fastest until something quicker replaces it. In Settings -> Data you can
delete just that run, a whole sector, or the whole track and car.

## When the game closes

The app watches for the game process and closes itself (saving first) as soon as the game exits,
within a second or so. This can be switched off in Settings.
