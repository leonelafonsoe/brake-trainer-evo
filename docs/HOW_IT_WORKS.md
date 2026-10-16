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

The lap is split into sectors, about one per kilometre (3 to 8 in total). Sectors exist so the
app can keep the **best** driving and so a mistake late in the lap does not cost you the good
part of it:

- Each sector is timed on its own.
- The moment you finish a sector, it is compared with your kept runs for that sector. If it is
  among your **3 fastest**, its braking points are saved straight away, even if you crash two
  corners later.
- The cue point for a corner is the **median** of the braking points in your kept runs, so one
  unusually late (or early) lap does not move it much. A corner has to appear in at least half of
  the kept runs to become a cue point.

### Where the sector lines are

Sector lines are not simply equal splits. A corner that sits on a line would be cut between two
sectors, and its braking point would flip between them from lap to lap. Instead, the warm-up lap
surveys where your braking zones are and the lines are moved to the middle of the nearest
straight (up to about a third of a sector away). The lines are stored with the track data and
shared with other cars, so a borrowed reference stays aligned.

**Data from older versions** (before 0.3.5) keeps the equal splits it was learned with, so a corner can
still be cut by a line. The overlay then shows "equal sector lines" in its quiet summary, and
Settings -> Data lists it as "equal splits". Delete that entry and drive a warm-up lap to place the
lines on the straights.

The start/finish line never moves, so a braking zone very close to it can still wobble between
the last and the first sector.

## A typical session

| When | What happens |
| --- | --- |
| You start the app | It waits for the game. The overlay opens at the top centre of the screen. |
| You leave the pits | **Warm-up lap**: nothing is learned (cold tyres and brakes make you brake early) but the app surveys the corners and places the sector lines. The status line says "Warm-up lap · not learning". |
| You cross the line | Learning starts. As soon as you finish the first sector it is saved and its colour appears. |
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

- **Warm-up**: it is part of a warm-up lap (see above).
- **Pit lane**: you were in the pit lane, or reset to the pits, during it.
- **Partial**: you reset or teleported mid-sector, or drove less than 90% of it.
- **Invalid lap**: the game invalidated your lap *while you were in that sector* (track limits,
  cuts). The game's "lap valid" flag drops once and stays down, so it can only mark the sector
  where the invalidation happened. Earlier sectors on the same lap are kept. A sector you *enter*
  after the lap was already invalid is kept too, as long as you stay on the track in it (see the
  next point).
- **Off track**: the game recorded an off-track while you were in that sector (Settings: "Skip sector
  if tyres off track", and "...once the lap is invalid"). This uses the game's per-excursion signal —
  the "race cut" pair it writes when a wheel goes off (time gained, distance left to give it back) —
  and, where the game publishes it, the live count of tyres off the track. It catches **every**
  excursion, including a second one in a later sector of a lap the game already invalidated, which the
  one-shot lap flag cannot show. While the lap is still valid the tyre count takes all four tyres (the
  game's own rule); once the lap is invalid a lower count (default 2) applies for the rest of that lap.
- **Paused**: learning was paused at any point during it.

The signals above are the game's own, read from its telemetry. When the game invalidates a lap for an
infraction it does not expose per violation (no race cut and no tyres reported off), the app says so
in its log and can only drop the sector where the flag dropped. See [TELEMETRY.md](TELEMETRY.md).

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

The colours are *not* the F1 meaning: there is no other driver to compare with, so purple is your
best and green is "good enough to count".

## The status line

The line under the sector bar shows the most relevant of these, top first:

1. A problem in the current sector (red): "S3 won't count · lap invalidated" or "off track".
2. "Learning paused" (amber).
3. "Warm-up lap · not learning" (amber).
4. The last sector result for 6 seconds, in the sector's colour: "S2 18.01 s · best".
5. "Reference: <car>" while borrowing another car's points (amber).
6. A quiet summary: "7 braking points", or "No braking points yet".

## New car on a known track

With no data of its own, a car **borrows the braking points of another car on the same track** as
a rough guide, matched by track position (so the other car's sector lines do not have to match yours). By default it picks the car with the most data (not the fastest,
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
