# Data files

Everything is stored per user in `%APPDATA%\BrakeTrainerEvo\`:

| Path | Content |
| --- | --- |
| `settings.json` | Your settings (see [SETTINGS.md](SETTINGS.md)) and the overlay position |
| `data\<track>__<car>.json` | What was learned for one track and car |
| `brake_trainer.log` | Log (rotated, about 0.5 MB x 3) |

Set the environment variable `BRAKE_TRAINER_HOME` to use another folder (handy for testing).

## Learned data format

```json
{
  "version": 1,
  "track": "Monza",
  "car": "Ferrari 296 GTB",
  "n_sectors": 3,
  "boundaries": [0.3205, 0.6324],
  "sectors": [
    [ {"t": 18.012, "onsets": [0.0431]}, {"t": 18.244, "onsets": [0.0436]} ],
    [],
    ...
  ],
  "early_onsets": [ [0.1762], [0.4823] ]
}
```

- `boundaries`: the `n_sectors - 1` inner sector lines (0..1). They are the game's own sector lines,
  learned from its log (see `DESIGN.md`); `null` means they have not been learned yet, so equal splits
  are in use - that is what files from versions before 0.3.11 use and keep. Settings -> Data shows
  which kind each entry is. The lines are the track's, not the car's, so an entry here is copied from
  another car's file on the same track as soon as it is opened, and only a track no car has learned yet
  waits for the log. To learn the lines again, delete every entry on the track and drive a lap.
- `sectors`: one list per sector, fastest run first. Each run has its time `t` in seconds and
  the track positions `onsets` where braking started in that run.
- `early_onsets`: positions where braking started on the passes that could not be timed because the
  sector lines were still being found, or had just changed under the car - one list per pass. Their
  times are worthless (the lines they would use are not known), but they are where the corners are, and
  on a new track they are all the cues there are until a sector has been timed. They vote as one run
  each, so the counted runs out-vote them as they arrive; when the pass they came from is retimed, its
  timed run carries them and the stand-in entry is removed. A sector the game invalidated, or one
  whose crossings are no longer in the kept samples, is never stored from its stand-in entry.
- Files whose `n_sectors` does not match the app's sector count (3) are ignored and replaced on the
  next save: files from 0.3.10 and earlier hold a different number of sectors.

## Housekeeping

- **Delete part of the data**: Settings -> Data shows each track and car as a tree: entry, then its
  sectors, then the runs kept for each sector. Select a single run (for example a time you got in a
  slipstream), a whole sector, or a whole entry, and press "Delete selected". Deleting an entry asks
  for confirmation. The change is applied by the running app itself, so it is not undone by the app
  saving its own copy.
- **Start over**: delete the files in `data\`.
- **Reset settings**: delete `settings.json`.
- **Share or back up data**: copy the files. They are plain JSON.
