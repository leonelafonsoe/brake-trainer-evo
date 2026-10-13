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
  "n_sectors": 6,
  "boundaries": [0.158, 0.331, 0.497, 0.662, 0.838],
  "sectors": [
    [ {"t": 18.012, "onsets": [0.0431]}, {"t": 18.244, "onsets": [0.0436]} ],
    [],
    ...
  ]
}
```

- `boundaries`: the `n_sectors - 1` inner sector lines (0..1). `null` means equal splits, which
  is what files from versions before 0.3.5 use and keep. Settings -> Data shows which kind each
  entry is. To move the lines to the straights, delete the entry and drive a warm-up lap.
- `sectors`: one list per sector, fastest run first. Each run has its time `t` in seconds and
  the track positions `onsets` where braking started in that run.
- Files whose `n_sectors` does not match the current sector count for that track are ignored
  and replaced on the next save.

## Housekeeping

- **Delete part of the data**: Settings -> Data shows each track and car as a tree: entry, then its
  sectors, then the runs kept for each sector. Select a single run (for example a time you got in a
  slipstream), a whole sector, or a whole entry, and press "Delete selected". Deleting an entry asks
  for confirmation. The change is applied by the running app itself, so it is not undone by the app
  saving its own copy.
- **Start over**: delete the files in `data\`.
- **Reset settings**: delete `settings.json`.
- **Share or back up data**: copy the files. They are plain JSON.
