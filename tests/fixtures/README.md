# Fixtures

Real data used as evidence, kept small. A fixture is the smallest excerpt that reproduces one
behaviour, with personal data removed.

- `game_log/` — exact lines the game wrote, used as parser inputs. See its README.
- `track_data/` — real stored `version: 1` JSON, used to check that the current loader still accepts
  files from older app versions.
- `settings/` — real settings JSON from older versions, used for one-time migrations.

App logs are not inputs: they are the app's own output. Use them to diagnose a report and to write
the expected scenario, but keep the test input synthetic. Do not commit full session logs.

Add `app_log/` only when a real case needs one, not as an empty folder.
