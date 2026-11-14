# Technical Design Specification — move telemetry to acevo-sdk 0.2.2

**Spec branch:** `deps/acevo-sdk-0.2`
**Base commit:** `77afec8ac41c6e881ddcf4db0f82d8acf1131280` (`main`, "Merge pull request #73 …")
**Repository:** `brake-trainer-evo`
**Status:** awaiting GO.

## Objective

Move the runtime dependency from `acevo-sdk` 0.1.1 (pinned `<0.2.0`) to the newest release,
**0.2.2**, and adopt the 0.2.2 capabilities that actually fit this app. This is an adaptation, not a
version bump:

- the capture paths the SDK no longer supports are shimmed, with tests;
- the penalty parser accepts the SDK's documented addition shape without losing our per-event,
  multiple-cuts-per-lap behaviour;
- frames from replay/pause/teardown are ignored using the SDK's state model;
- learned data is keyed by the track's configuration, using the SDK's catalog, without breaking the
  keys existing data already uses;
- Dependabot, docs, changelog and roadmap describe the new state.

## Dependency review (14 November 2026)

Sources read before designing the change:

- PyPI metadata and release files for `acevo-sdk` 0.1.1, 0.2.0, 0.2.1 and 0.2.2
  (<https://pypi.org/project/acevo-sdk/#history>); 0.2.2 was published 2026-11-08 and is the
  newest release.
- The upstream `CHANGELOG.md` and the GitHub release notes for v0.2.0, v0.2.1 and v0.2.2
  (<https://github.com/glebulon/acevo-sdk/releases>).
- The upstream README, public exports (`src/acevo/__init__.py`) and the 0.1.1 → 0.2.2 source diff
  of `capture.py`, `decoder.py`, `models.py`, `shared_session.py`, `logs.py`, `constants.py` and
  `catalogs/`.
- The upstream regression tests and fixtures at tag `v0.2.2`, including the penalty-line cases.
- The upstream fixture pair `tests/fixtures/ac_evo_graphics_frame.txt` and
  `ac_evo_static_frame.txt` at tag `v0.2.2`, decoded with both 0.1.1 and 0.2.2.

### Release notes that matter

| Release | Note | Bearing on this app |
|---|---|---|
| 0.2.0 | ACE v0.7 log format, log-authoritative lap detection, validity handling | We do not use `LogParser`; only the per-event lines and the capture frame shape matter. |
| 0.2.0 | **Breaking:** `LapState.PUSH` renamed `LapState.VALID` | Not imported anywhere in this repository. No code change. |
| 0.2.0 | Validity-only capture, `CaptureSnapshot`, `LapBoundary`, `peek_graphics_validity` | Not used; opt-in APIs. |
| 0.2.0 | Graphics decoder sanity checks, static-payload sanitisation, dropped legacy ACC fields | All keys this app reads still exist; checked below. |
| 0.2.1 | Multiplayer log-parser fixes | The app's parser reads only split/cut lines; no bearing. |
| 0.2.2 | Race-weekend sub-session type fix | No bearing. |

### Three capture behaviours this adapter must replace

1. **The frame-recording gate.** `TelemetryCapture.start_capture()` now does
   `self._recording_awaiting_boundary = self._record_frames` (0.2.2 `src/acevo/capture.py:948`),
   and the capture loop appends a frame only when that flag is false (`:1081-1082`). With the
   default `record_frames=True`, `get_frames()` is **empty until the next clean lap boundary**.
   The live overlay and learning would see nothing for a whole outlap. The SDK's own tests release
   the flag directly to simulate a live recorder (`tests/test_telemetry_capture_coverage.py:558-595`).
2. **Raw region bytes are dropped.** With `debug_logs=False` (our default), `_capture_frame()`
   nulls `physics_raw`, `graphics_raw` and `static_raw` before returning the frame
   (0.2.2 `src/acevo/capture.py:899-905`). The race-cut pair is not decoded into `graphics`, so the
   current adapter's only source (`frame.graphics_raw`) disappears. The SDK still defines the
   offsets: `_GE_RACE_CUT_GAINED_TIME_MS = 2464`, `_GE_DISTANCE_TO_DEADLINE = 2468`,
   `_GE_RACE_CUT_CURRENT_DELTA = 2472` (0.2.2 `src/acevo/decoder.py:735-737`; identical in 0.1.1
   `decoder.py:689-691`), so the bytes can be read from the same mapping.
3. **The 120 s idle timeout is gone.** `IDLE_TIMEOUT_SECONDS` exists in 0.1.1
   (`capture.py:221-224`) and does not exist in 0.2.0-0.2.2.

### Compatibility evidence for the keys this app consumes

The upstream 0.2.2 fixture (`ac_evo_graphics_frame.txt`, SHA-256
`36ff5d3b02fbfa8b44c022c43a8dbd0ed53b0ecbbc5792337fda14955d8a0fb8`) decoded with 0.1.1 and 0.2.2
returns identical values for every key the app reads:

| Key | 0.1.1 | 0.2.2 |
|---|---|---|
| `normalized_car_position` | `0.03607041761279106` | same |
| `car_model` | `Dallara EXP` | same |
| `is_valid_lap` | `True` | same (offset 3121 unchanged) |
| `is_invalid` / `timing_is_invalid` | `False` | same (the SDK moved its offset 2822 → 2849 itself) |
| `is_in_pit_lane` / `is_in_pit` | `False` / `False` | same |
| `lap_length_km`, `status_name`, `completed_laps`, `current_lap_time_ms` | present | same |
| `static.track`, `static.track_length_m` | `Brands Hatch`, `1944.0` | same |
| `static.track_configuration` | `Indy` | same |
| race-cut triple at 2464/2468/2472 | `(0, 0, 0.0)` | same offsets, same read |

`sample_from_frame()` keeps the same field-level contract. The 0.2.2 sdist reports
`acevo.__version__ == "0.2.1"` (an upstream packaging slip); the lock is the version of record and
the app must not use that string.

### Empirical check of the frame gate

Running the 0.2.2 capture loop on Linux with a stubbed frame source:

- gate left as `start_capture()` sets it → `get_frames()` = `[]`;
- gate cleared → `get_frames()` = `[0, 1, 2]`.

This is the exact change the adapter makes, and it is why the workaround is not a guess.

## Adoption review: what 0.2.2 makes better, and what stays

I audited every manual path against the new public API. The verdict:

| Area | What we do now | 0.2.2 offer | Decision |
|---|---|---|---|
| Live frames | Poll `get_frames()` | A lap-boundary gate; no public streaming mode | **Shim** (T1). No better public path; upstream request. |
| Race-cut pair | Read raw graphics bytes | Offsets still defined, fields still not decoded; raw bytes dropped in normal capture | **Shim** (T1). No public accessor; upstream request. |
| Idle timeout | Patch `IDLE_TIMEOUT_SECONDS` | Removed | **Adopt removal** (T1). |
| Penalty events | Match `Adding notification UINotificationType_SessionPenalty` | Documented `true {PENALTY_ADDED_KEY}` addition and `false {PENALTY_CLEARED_KEY}` clearance shapes | **Adopt both addition shapes; ignore clearances; keep per-event parsing** (T2). |
| Frame state | Accept anything with position/track/car | `status`/`status_name` state model (`AC_OFF`, `AC_REPLAY`, `AC_LIVE`, `AC_PAUSE`) | **Adopt a live-only filter** (T3). |
| Track identity | Raw `static.track` key, configuration ignored | `resolve_track_key()` and a catalog with per-track default configurations | **Adopt configuration-aware keys, backward-compatible** (T4). |
| Game-log tail | Own tailer with inode/rewrite detection, skip-history and line times | `LogParser.follow()` parses sessions/laps, but exposes no per-line callback and no absolute split/cut times (`InProgressLap.splits` is durations) | **Keep.** Adopting it would lose the line-time attribution the engine depends on. |
| Lap/session results | Not tracked | `LapData`/`SessionData`, `SharedSessionManager`, `LapCompletionData` | **Not adopted.** They answer "what was the lap result?", not "where did this cut happen?". |
| `peek_graphics_validity()` | Full frame decode already gives `is_valid_lap` | Lightweight validity peek | **No gain.** |
| `game_running_callback`, stop callbacks, `CaptureSnapshot`, `configure()` | Own watcher and flush-once watchdog, with tests | Hooks and output controls | **No gain / duplicate authority.** |
| `LapBoundary` / `record_lap_boundary()` | Sector timing from telemetry crossings | Analysis boundaries for retained frames | **No fit.** |
| Car tuning catalog / `is_hybrid_car()` | Not used | Setup and hybrid helpers | **Out of domain.** |

### Why the penalty model stays per-event

The app cares about **the off-track itself**, not the penalty state. A cleared penalty does not
undo the excursion: the braking point and line through that sector were compromised, so the sector
still should not count. We only need to avoid treating a *clearance line* as a second excursion.

The SDK's lap-level validity cannot represent several cuts in one lap: `is_valid` is one latch per
lap. This app deliberately uses one event per addition and attributes each to the sector at its own
line time; the engine already folds overlapping signals by `(lap, sector)` so one cut drops one
sector while two cuts in different sectors each drop their own. Replacing that with the SDK's
lap-level model would lose the second cut.

The SDK's warning-line rule is also **not current for our game build**. Running the 0.2.2 parser
over our real 0.9.1 cut fixture (`tests/fixtures/game_log/notification_block.txt`) leaves
`_pending_penalty_warning` false, while the SDK's `true {PENALTY_ADDED_KEY}` line sets it true:

```text
pending_penalty_warning after our real cut block: False
pending_penalty_warning after SDK's ADDED line: True
```

So adopting the SDK's rule alone would make our current build's cuts invisible. T2 keeps our
addition line and adds the SDK's, ignores both clearance shapes, and adds no blanket 15 s dedup:
a 15 s window would also suppress a legitimate second cut in a different sector. The engine's
`(lap, sector)` folding remains the duplicate rule. A field check covers a cut followed by a
race-mode give-back.

### The two capture shims stay because no public API replaced them

`record_frames=False` gives no frames, `debug_logs=True` writes debug dumps and builds hex strings
per frame, `record_lap_boundary()` invents a boundary, and a custom `SharedSessionManager` would
re-implement the frame buffer through a session hook while still needing raw bytes. The two shims
are the smallest dependency on 0.2.2 internals; the tripwire tests make a future change loud.

## Non-goals

- No adoption of `LogParser`, `SharedSessionManager`, `LapBoundary`, `peek_graphics_validity` or
  `CaptureSnapshot`; the per-event timing requirements above rule them out.
- No blanket time-based penalty dedup: it would suppress legitimate multiple cuts in one lap.
- No full track-name canonicalization or data-key migration. T4 keeps existing default-config keys
  and only adds a configuration suffix for non-default layouts; a name variant the catalog cannot
  resolve keeps its raw name. A full canonical migration is a separate storage change.
- No version bump, no release, no changelog version section. A release is a separate task.
- No recalibration of the race-cut offsets, and no new game measurements. The offsets are
  corroborated by the SDK source, not re-derived here.
- No change to `DATA_VERSION` or `SETTINGS_VERSION`; no engine rewrite.
- No `game_running_callback` injection: the app's process watcher already owns game-exit detection.

---

## Task 1 — Pin 0.2.2 and adapt the capture adapter

**Task ID:** T1
**Depends on:** nothing.

### Outcome

The project installs and ships `acevo-sdk` 0.2.2. The live overlay and learning receive frames from
the first frame of an outlap, the race-cut pair is still read from the graphics region, and the
adapter no longer patches a timeout that does not exist.

### Current behaviour

- `pyproject.toml:21-22` pins `acevo-sdk>=0.1.1,<0.2.0`; `uv.lock` resolves 0.1.1.
- `src/brake_trainer/telemetry.py:210-218` constructs `TelemetryCapture(hz=hz)` and sets
  `TelemetryCapture.IDLE_TIMEOUT_SECONDS = inf`.
- `telemetry.py:145-175` reads `frame.graphics_raw` (hex text) for the race-cut triple; 0.2.2
  returns `None` there in normal mode, so the pair would silently become `(0, 0, 0.0)`.
- `telemetry.py:352-357` polls `get_frames()`; with 0.2.2's gate it would stay empty until a lap
  boundary.
- `tests/test_telemetry_audio.py` feeds hex `graphics_raw` into `sample_from_frame()`, and the
  flaky-frame test monkeypatches `sample_from_frame(frame)` with one argument.

### File map

| File | Change |
|---|---|
| `pyproject.toml` | pin `acevo-sdk>=0.2.2,<0.3.0`; replace the stale pin comment |
| `uv.lock` | regenerate with `uv lock --upgrade-package acevo-sdk`; resolves 0.2.2 |
| `src/brake_trainer/telemetry.py` | live-capture proxy; graphics-region reader; byte-based race-cut parse; stop patching the idle timeout |
| `tests/test_telemetry_audio.py` | update race-cut tests; add gate, proxy, region-reader and integration tests; fix the flaky signature |

Nothing else. `docs/plans/acevo-sdk-0.2.md` is committed by itself before T1 and is not part of the
T1 diff.

### Design

1. **Pin and lock.** In `pyproject.toml`, set
   `dependencies = ["PySide6>=6.6,<7", "acevo-sdk>=0.2.2,<0.3.0"]`. Replace the comment above it
   with a short, true one: 0.2 hides the frame buffer behind a lap-boundary gate and drops raw
   region bytes in normal capture; `telemetry.py` releases the gate and reads the graphics region
   itself. Run `uv lock --upgrade-package acevo-sdk` (never edit `uv.lock` by hand) and
   `uv sync --locked --extra dev`. Report
   `uv run python -c "import importlib.metadata as m; print(m.version('acevo-sdk'))"` → `0.2.2`.
   The `uv.lock` diff must not move any other package.

2. **`_LiveCapture` proxy.** Add a module-level wrapper around the default capture:

   - `__init__(self, capture: Any)`;
   - `async start_capture(self) -> bool`: await the inner capture, then set
     `self._capture._recording_awaiting_boundary = False`, and return the inner result. Add a
     comment naming the 0.2.2 line and why the overlay needs the outlap. No `await` between the
     inner return and the assignment.
   - Delegate `is_capturing()`, `get_stop_reason()`, `get_frames()`, `clear()`,
     `stop_capture()` and `get_metadata()` explicitly; no `__getattr__`.
   - `_default_capture_factory(hz)` imports `TelemetryCapture` lazily, removes the
     `IDLE_TIMEOUT_SECONDS` assignment and its comment, and returns
     `_LiveCapture(TelemetryCapture(hz=hz))`.
   - Do not call `set_record_frames()` or `record_lap_boundary()`.

3. **Graphics-region reader.** Add:

   - `_GraphicsReader`: lazily opens the graphics mapping. Constructor takes
     `open_reader: Callable[[], Any] | None = None` and
     `clock: Callable[[], float] = time.monotonic`; a failed open is retried at most once a second;
     a read failure closes the reader so the next `read()` reopens. `read()` returns
     `bytes | None`; `close()` is idempotent.
   - `_open_graphics_region()`: imports `RegionReader` from `acevo` and `REGIONS` from
     `acevo.capture`, builds `RegionReader(*REGIONS["graphics"])`, calls `open()`, and returns the
     reader or `None`. Catch exceptions and return `None`.
   - A `_GraphicsSource` `Protocol` for typing and test injection.

4. **Wire the reader into `TelemetryReader`.** Add keyword-only
   `graphics_reader: Callable[[], _GraphicsSource] = _GraphicsReader`. In `run()`:

   - create a reader when a capture starts successfully;
   - close it when the capture stops, when the read path fails and capture is torn down, and in the
     `finally` block;
   - after `frames = cap.get_frames()` / `cap.clear()`, call `graphics.read()` **once per poll**
     when there are frames, and pass the bytes to `_deliver(frames, raw_graphics)`;
   - a `None` means "no cut data this poll" and is not an error.

5. **Byte-based race-cut parse.** Change `_race_cut(frame)` to `_race_cut(raw: bytes | None)`:
   read 12 bytes at `_GFX_RACE_CUT_OFFSET` (2464), unpack `<ii f`, keep the plausibility bounds.
   `sample_from_frame(frame, raw_graphics: bytes | None = None)` calls it. Remove every use of
   `frame.graphics_raw` from `src`. Update the module comment above the offsets.

6. **Keep the rest unchanged:** `TRACK_LIMITS_NOTE`, the watchdog, game-exit detection, status
   messages, and the engine contract.

### Tests

All in `tests/test_telemetry_audio.py`.

Update:

- `_raw_graphics()` returns `bytes`; the race-cut test passes the bytes as the second argument.
- The corrupt-input cases become bytes cases; keep the shifted-but-plausible case.
- The `flaky(frame)` monkeypatch accepts `(frame, raw_graphics=None)`.
- `FakeCapture.get_stop_reason()` returns `"heartbeat_timeout"`, not `"idle_timeout"`.

Add:

1. `test_the_sdk_still_arms_the_frame_gate_after_start` — construct `TelemetryCapture(hz=1)`,
   `await start_capture()`, assert `_recording_awaiting_boundary is True`, `stop_capture()` in
   `finally`. If the SDK now streams frames, remove the workaround and this test.
2. `test_the_sdk_still_publishes_the_graphics_region` — `REGIONS["graphics"]` is a non-empty name
   and a positive size.
3. `test_the_live_capture_releases_the_frame_gate` — fake inner sets the flag; the proxy clears it.
4. `test_the_live_capture_delegates_the_capture_api` — every delegated method reaches the inner.
5. `test_graphics_reader_reads_once_open`.
6. `test_graphics_reader_retries_a_failed_open_at_most_once_a_second` (injected clock).
7. `test_graphics_reader_reopens_after_a_failed_read`.
8. `test_graphics_reader_close_is_idempotent`.
9. `test_open_graphics_region_reports_a_missing_region` and
   `test_open_graphics_region_returns_an_open_reader` (monkeypatch the SDK's `RegionReader`).
10. `test_sample_ignores_the_sdk_graphics_raw_field` — only the explicit bytes are the source.
11. `test_reader_attaches_the_live_race_cut_to_every_sample` — two frames, one injected 320 ms /
    150 m / -0.42 block; every sample carries it, and the source is closed at the end.

### Acceptance criteria

1. `pyproject.toml` pins `acevo-sdk>=0.2.2,<0.3.0`; the comment states the gate and raw-bytes
   workarounds.
2. `uv.lock` resolves 0.2.2; `uv sync --locked --extra dev` succeeds; the distribution reports
   0.2.2; the lock diff moves no other package.
3. `src/brake_trainer/telemetry.py` contains no `IDLE_TIMEOUT_SECONDS` and no
   `frame.graphics_raw` read.
4. `_LiveCapture.start_capture()` clears `_recording_awaiting_boundary` after the inner start;
   the proxy delegates every capture call the reader uses.
5. `_GraphicsReader` opens lazily, retries a failed open no faster than once a second, closes after
   a failed read, and never raises out of `read()`/`close()`.
6. `sample_from_frame()` takes raw bytes explicitly; the race-cut parse keeps the bounds and the
   2464/2468/2472 offsets.
7. `TelemetryReader.run()` closes the graphics source on stop, read failure and exit, and reads it
   at most once per poll.
8. Every new or changed test above passes, including on Windows.
9. Fast gate passes:
   `uv run ruff format --check .` → `uv run ruff check .` → `uv run mypy` →
   `uv run pytest -q -W error tests/test_telemetry_audio.py`.
10. `git status --porcelain --untracked-files=all` lists only the four mapped files (plus the spec
    file if it was committed by itself).

### Rollback

Revert the T1 commit: restore the `<0.2.0` pin and 0.1.1 lock, return `_race_cut()` to reading
`frame.graphics_raw`, restore the `IDLE_TIMEOUT_SECONDS` patch, and drop the proxy, reader and tests.
No data format changes.

---

## Task 2 — Accept the SDK's penalty addition shape without losing multiple cuts

**Task ID:** T2
**Depends on:** T1 (the project is on 0.2.2).

### Outcome

The parser reports a cut for both documented addition shapes — our build's
`Adding notification UINotificationType_SessionPenalty` and the SDK's
`true {PENALTY_ADDED_KEY}` — ignores both clearance shapes, and still reports every addition in a
lap, so two off-tracks in different sectors each drop their own sector. No blanket time dedup is
introduced.

### Current behaviour

`src/brake_trainer/gamelog.py:54` matches only `Adding notification UINotificationType_SessionPenalty`.
The SDK's `true {PENALTY_ADDED_KEY}` line is not matched; the `false {PENALTY_CLEARED_KEY}` line is
ignored. The engine folds overlapping signals by `(lap, sector)` (`engine/limits.py:148-151`), so
multiple additions in different sectors already work.

### File map

| File | Change |
|---|---|
| `src/brake_trainer/gamelog.py` | match both addition shapes; ignore clearance shapes; document the multiple-cut rule |
| `tests/test_gamelog_parser.py` | tests for both addition shapes, the clearance line, and two additions in one lap |
| `tests/fixtures/game_log/penalty_sdk_build.txt` | new small excerpt with one SDK-shaped addition and one clearance line |
| `tests/fixtures/game_log/README.md` | note the provenance of the new fixture |

Nothing else.

### Design

1. Add `_PENALTY_ADDED_RE = re.compile(r"\{PENALTY_ADDED_KEY\}")` next to `_NOTIFY_RE`.
   `parse_line` returns `LogEvent(cut=REPORTED_CUT)` when either regex matches. A
   `{PENALTY_CLEARED_KEY}` line and a plain `UINotification` line without `Adding` match neither and
   stay silent.
2. Do **not** add a 15 s time window. The SDK uses one because its model is one lap-level validity
   latch; this app attributes every event at its own line time and already folds a duplicate that
   lands in the same sector. A blanket 15 s window would suppress a real second cut in another
   sector, which is exactly the behaviour the app needs. If a cross-sector duplicate is observed in
   the field, it gets its own evidence and rule.
3. Keep the fixture rule: `notification_block.txt` is our real 0.9.1 cut; record that the SDK's
   parser does not recognise it, so the new fixture is the SDK-shaped build, not a replacement.
   The new fixture contains exactly two event lines:
   `[2026-08-18 23:13:02.935] [gameface] [warning] true {PENALTY_ADDED_KEY} #0` and
   `[2026-08-18 23:13:20.000] [gameface] [warning] false {PENALTY_CLEARED_KEY} #296`, both from
   the SDK's 0.2.2 regression data; the README says so.
4. No engine change. The engine's `(lap, sector)` folding and its per-event attribution stay as
   they are.

### Tests

- Existing `test_a_real_monza_notification_block_reports_one_cut_after_its_split` still passes.
- `test_the_sdk_penalty_addition_is_a_cut` — the exact `true {PENALTY_ADDED_KEY}` line from the
  SDK's regression test returns a cut.
- `test_the_penalty_clearance_line_is_not_a_cut` — `false {PENALTY_CLEARED_KEY}` returns `None`
  (the existing test already covers this; keep it).
- `test_a_plain_notification_without_adding_is_not_a_cut` — the `UINotification` line alone is
  silent.
- `test_two_additions_in_one_lap_are_both_reported` — two addition lines at different timestamps
  produce two cut events, proving no time dedup.
- `test_the_sdk_shaped_fixture_reports_only_its_addition` — the new fixture yields exactly one cut.

### Acceptance criteria

1. `parse_line` returns a cut for `Adding notification ... SessionPenalty` and for
   `{PENALTY_ADDED_KEY}`; returns `None` for `{PENALTY_CLEARED_KEY}` and for a plain
   `UINotification` line.
2. Two addition lines at different times produce two events; no time-based suppression exists.
3. The new fixture and README note are present; the existing Monza fixtures and tests are unchanged.
4. Fast gate passes:
   `uv run ruff format --check .` → `uv run ruff check .` → `uv run mypy` →
   `uv run pytest -q -W error tests/test_gamelog_parser.py tests/test_cut_attribution.py`.
5. Only the four mapped files changed.

### Rollback

Revert the T2 commit. The parser returns to matching only our build's addition line; the SDK's
line is ignored again. No data or engine change.

---

## Task 3 — Ignore frames from replay, pause and teardown

**Task ID:** T3
**Depends on:** T1.

### Outcome

A frame whose graphics state is not `AC_LIVE` is not turned into a sample, so a replay, a pause or a
teardown cannot teach braking points or drive cues. Live frames, and frames from builds without a
status field, behave exactly as before.

### Current behaviour

`sample_from_frame()` accepts any frame with a mapping physics/graphics/static, a
`normalized_car_position`, and a track/car name. A replay of a valid lap has all of those, so it can
be learned. The SDK's 0.2 state model names the states: `status` 0 `AC_OFF`, 1 `AC_REPLAY`,
2 `AC_LIVE`, 3 `AC_PAUSE` (`decoder.py:1121`, `shared_session.py:28`).

### File map

| File | Change |
|---|---|
| `src/brake_trainer/telemetry.py` | a live-only check in `sample_from_frame()` |
| `tests/test_telemetry_audio.py` | status/name cases, including the backwards-compatible missing case |

Nothing else.

### Design

1. Add `_live_frame(gfx: Mapping[str, Any]) -> bool`:
   - if `gfx.get("status")` is an `int` (not `bool`): live only when it is `2`;
   - else if `status_name` is a non-empty string: live only when it is `AC_LIVE`
     (case-insensitive);
   - else true, so a build without the field keeps working.
2. Call it in `sample_from_frame()` after the mapping checks and before building the `Sample`;
   return `None` when not live. Do not add cues or status messages for this; a replay simply
   produces no samples.
3. Keep the existing track/car/position checks; this is an additional filter, not a replacement.

### Tests

- `AC_LIVE` (status 2 and name) yields a sample.
- `AC_REPLAY` (status 1 and name-only) yields `None`.
- `AC_PAUSE` (status 3) yields `None`.
- `AC_OFF` (status 0) yields `None`.
- A frame with neither `status` nor `status_name` still yields a sample.
- A `status_name` of `AC_LIVE` with a numeric status of 1 is rejected: the numeric field wins.
- Existing `sample_from_frame` tests keep passing unchanged.

### Acceptance criteria

1. `sample_from_frame()` returns `None` for `AC_OFF`, `AC_REPLAY` and `AC_PAUSE`, whether the
   state comes from `status` or `status_name`.
2. `AC_LIVE` and a missing status both yield the same sample as before.
3. The existing tests are unchanged except for the new cases.
4. Fast gate passes:
   `uv run ruff format --check .` → `uv run ruff check .` → `uv run mypy` →
   `uv run pytest -q -W error tests/test_telemetry_audio.py tests/test_cut_attribution.py`.
5. Only the two mapped files changed.

### Rollback

Revert the T3 commit; the status filter disappears and every otherwise-valid frame is sampled
again. No data format change.

---

## Task 4 — Key learned data by track configuration

**Task ID:** T4
**Depends on:** T1 (the catalog comes from 0.2.2).

### Outcome

Learned data for an alternate layout of a track is stored separately from the default layout. The
default layout, tracks the catalog does not know, and all existing data keep the exact keys they
already use. The Windows build bundles the catalog data so this works in the frozen app.

### Current behaviour

`sample_from_frame()` uses only `static.track` as `Sample.track`; `static.track_configuration` is
ignored. `TrackStore` and the engine key learned data on `(Sample.track, Sample.car)`. On a track
with several layouts (for example Brands Hatch GP and Indy), the game reports the same
`static.track` and a different `track_configuration`, so the two layouts share braking points.
`scripts/build_exe.py` collects `acevo` submodules but not package data, so the catalog JSON would
not be in the frozen app.

### File map

| File | Change |
|---|---|
| `src/brake_trainer/telemetry.py` | configuration-aware `Sample.track` label |
| `scripts/build_exe.py` | collect the `acevo` package data (the track catalog) |
| `tests/test_telemetry_audio.py` | default/alternate/unknown/missing-catalog cases |
| `tests/test_release_tools.py` | assert the build collects the SDK data |

Nothing else. No `TrackData`/`Sample` schema change, no `DATA_VERSION` change, no storage change:
`Sample.track` remains the display label and the store key.

### Design

1. Add a cached `_default_config(track: str) -> str` in `telemetry.py`:
   - import `resolve_track_key` and `find_track_by_name` from `acevo.catalogs` lazily;
   - resolve the key; if none, return `""`;
   - return the profile's `config_key` (the catalog's default configuration);
   - catch any exception and return `""`, so a missing catalog degrades to the old behaviour.
   Cache per track name; the catalog is static.
2. Add `_track_label(track: str, configuration: str) -> str`:
   - empty configuration → `track`;
   - unknown track (no default config) → `track`;
   - configuration equal to the default (case-insensitive) → `track`;
   - otherwise `f"{track} [{configuration}]"`.
3. In `sample_from_frame()`, read `static.get("track_configuration")` and set
   `track = _track_label(str(track), str(configuration))`. The label stays the store key and the
   display name, so the Data tab shows `Brands Hatch [Indy]` for the alternate layout.
4. Add `--collect-data`, `acevo` to the PyInstaller command in `scripts/build_exe.py`, next to
   `--collect-submodules`. The catalog's `_load_catalog()` already falls back to a path next to the
   module, so both one-file and one-dir builds work once the data is collected.
5. Backward compatibility: a default-layout track keeps the raw game name, so existing files load
   unchanged. An alternate layout gets a new key and starts fresh; the old base-key entry is left
   untouched (never deleted), and the user can still see or delete it in the Data tab. A track the
   catalog cannot resolve keeps the raw name, so it can still mix layouts; that is documented rather
   than guessed.

### Tests

- `static.track="Brands Hatch"`, `track_configuration="Indy"` → `Sample.track ==
  "Brands Hatch [Indy]"`.
- `track_configuration="GP"` (default) → `"Brands Hatch"`.
- Empty/absent configuration → the raw track.
- Unknown track plus a configuration → the raw track.
- `_default_config` is called once per track (cache) — optional, but a direct unit test of the
  helper is enough.
- Catalog import/lookup failure (monkeypatch `acevo.catalogs` import) → the raw track.
- `build_exe.py` contains `--collect-data` and `acevo` (a text assertion in
  `tests/test_release_tools.py`, next to the existing `--add-data` assertion).

### Acceptance criteria

1. A non-default `track_configuration` appends ` [<configuration>]` to `Sample.track`; a default
   configuration and an unknown track leave it unchanged.
2. The value is the store key and display label; no `TrackData`/`Sample` field or
   `DATA_VERSION` changed.
3. Existing default-layout data loads under the same key; alternate layouts use a different key.
4. The catalog lookup is lazy, cached, and failure-safe.
5. `scripts/build_exe.py` collects `acevo` package data; the `windows-build` check still passes.
6. Fast gate passes:
   `uv run ruff format --check .` → `uv run ruff check .` → `uv run mypy` →
   `uv run pytest -q -W error tests/test_telemetry_audio.py tests/test_release_tools.py`.
7. Only the four mapped files changed.

### Rollback

Revert the T4 commit. `Sample.track` returns to the raw game name, the catalog is not consulted, and
the build-script data flag disappears. Existing data and default-layout keys are unaffected; the
alternate-layout entries written under the suffixed key are left in place, not deleted.

---

## Task 5 — Dependabot policy, docs, changelog and roadmap

**Task ID:** T5
**Depends on:** T1-T4.

### Outcome

Dependabot watches `acevo-sdk` 0.2.x patches again, and every document that names the old pin, idle
timeout, raw-frame source, frame acceptance, penalty rule or track key states the new truth. The
changelog and roadmap record the move.

### Current behaviour

- `.github/dependabot.yml:8-13` ignores `versions: ["0.2.x"]` with a stale comment.
- `tests/test_release_tools.py:292-296` enforces the ignore rule.
- `docs/DEVELOPMENT.md:31` says the SDK is "pinned below 0.2.0".
- `docs/GAME_DATA.md:24` names `graphics.race_cut_*`; `:97-100` describes the raw-block read;
  `:153-155` says the app disables a 120 s idle timeout; it says nothing about replay states or
  track configurations.
- `docs/ROADMAP.md:7-40` lists the SDK move as pending.
- `CHANGELOG.md:5` has an empty `## Unreleased`.

### File map

| File | Change |
|---|---|
| `.github/dependabot.yml` | remove the `acevo-sdk` `ignore` block |
| `tests/test_release_tools.py` | replace the ignore test with the new pin policy |
| `docs/DEVELOPMENT.md` | update the runtime-dependency sentence |
| `docs/GAME_DATA.md` | update the fields table, penalty rule, frame states, track key and idle behaviour |
| `docs/GUIDE.md` | state the user-visible track-label and replay/pause behaviour |
| `docs/ROADMAP.md` | mark the move done; update the state and next release |
| `CHANGELOG.md` | add the move and the adopted behaviours under `## Unreleased` |

Nothing else.

### Design

1. **Dependabot.** Delete the `ignore:` entry and its comment under the `uv` ecosystem. Leave the
   `uv`, `github-actions` and `pre-commit` blocks unchanged. The `<0.3.0` pin excludes 0.3.
2. **Policy tests.** Replace
   `test_dependabot_ignores_the_incompatible_acevo_release` with
   `test_dependabot_watches_acevo_patch_releases` (no `dependency-name: acevo-sdk` entry) and
   `test_acevo_is_pinned_to_the_reviewed_minor_line` (parse `pyproject.toml` with `tomllib`; assert
   `acevo-sdk>=0.2.2,<0.3.0`). Keep `test_dependabot_covers_uv_and_actions`.
3. **`docs/DEVELOPMENT.md`.** Replace the "below 0.2.0" sentence with the 0.2.2 pin and a pointer
   to the pin comment.
4. **`docs/GAME_DATA.md`.**
   - Fields table: track/car row names `static.track` plus `static.track_configuration`; race-cut
     row states the bytes come from the graphics region read through `RegionReader` because 0.2
     drops `graphics_raw` in normal capture.
   - Track-limits section: both addition shapes are cuts; a `{PENALTY_CLEARED_KEY}` line is not an
     excursion; every addition in a lap is attributed at its own line time, so multiple cuts in
     different sectors each drop their own; no blanket dedup.
   - Frame acceptance: replay, pause and teardown frames are ignored; menus were already rejected.
   - Track key: default layouts and unknown tracks keep the raw name; a non-default configuration
     gets ` [config]`; existing data is not deleted.
   - Behaviours: replace the idle-timeout bullet with the true 5 s heartbeat / 3 s disconnect
     behaviour and note the 120 s timeout was removed in 0.2.
5. **`docs/GUIDE.md`.** One short paragraph: an alternate layout appears as `Track [Config]` in the
   Data tab and learns separately; replay/pause do not teach.
6. **`docs/ROADMAP.md`.** Record the move as done; remove it from the immediate queue; state that
   the 0.8.0 (or chosen) release is a separate task. Do not invent a PR number; do not announce an
   uncut version. Dependabot #65 is superseded and closed as part of delivery.
7. **`CHANGELOG.md`.** Under `## Unreleased`, add a `### Changed` block covering: `acevo-sdk` 0.2.2;
   outlap frames released from the gate; graphics region read directly for the race-cut pair;
   both penalty addition shapes accepted and clearances ignored without losing multiple cuts;
   replay/pause/teardown frames ignored; alternate track layouts keyed separately; the obsolete
   idle-timeout patch removed. No version heading.

### Tests

- `uv run pytest -q -W error tests/test_release_tools.py tests/test_docs.py`
- The docs link checks cover the existing pages; no new docs page is added.

### Acceptance criteria

1. `.github/dependabot.yml` has no `dependency-name: acevo-sdk` entry and no `0.2.x` ignore.
2. The two replacement policy tests exist and pass; the old ignore test is gone.
3. `docs/DEVELOPMENT.md` states the 0.2.2 pin and no longer says "below 0.2.0".
4. `docs/GAME_DATA.md` covers the penalty shapes, multiple cuts, frame states, track key and the
   removed idle timeout; it keeps the 2464/2468/2472 offsets and the plausibility bounds.
5. `docs/GUIDE.md` states the alternate-layout label and replay/pause behaviour.
6. `docs/ROADMAP.md` records the move as done and the release as separate.
7. `CHANGELOG.md` has the bullet(s) under `## Unreleased` and no version bump.
8. Fast gate passes:
   `uv run ruff format --check .` → `uv run ruff check .` → `uv run mypy` →
   `uv run pytest -q -W error tests/test_release_tools.py tests/test_docs.py`.
9. Only the seven mapped files changed.

### Rollback

Revert the T5 commit. Dependabot will ignore 0.2.x again while the code is on 0.2.2, and the docs
will describe the old state; that is inconsistent but harmless at runtime. Reverting T1-T4 as well
restores the old pin and the ignore rule together.

---

## Delivery

- **Repository:** `brake-trainer-evo` only.
- **Branch:** `deps/acevo-sdk-0.2`, created from `main` at `77afec8`. T1-T5 are commits on this
  branch; one PR.
- **Deploy:** none. Nothing is deployed or staged from a PR.
- **Candidate step:** required, because this changes the Windows-only telemetry and learning path.
  It is a human step that the loop cannot perform. After the required checks pass, download the
  PR's `windows-build` artifact and drive it in-game. Merge only after the session; if it is
  skipped, the report says so and the PR is **not** merged.
- **Candidate checks:**
  1. Start the app before the game, enter a practice session and leave the pits. The overlay moves
     and learning starts during the **outlap**, without waiting for a lap boundary.
  2. Drive a clean lap; sector lines are learned and saved; relaunching loads the data.
  3. Two deliberate cuts in different sectors of one lap each drop their own sector, and only those.
  4. Cut once, then give the time back in race mode if the mode offers it. The original cut sector
     stays dropped; the give-back position does not add a sector. If the build emits a clearance
     line that our parser counts, report it with the excerpt.
  5. Enter replay, pause, then resume. No samples or cues are produced from the replay or the pause;
     live driving resumes normally.
  6. On a track with two layouts (for example Brands Hatch GP and Indy), drive both. The Data tab
     shows separate entries (`Brands Hatch` and `Brands Hatch [Indy]`), and the default-layout entry
     loads its existing data. The frozen app must show the suffixed label, which proves the catalog
     data is bundled.
  7. Wait in the pits for more than two minutes without moving. Capture continues; no idle stop.
  8. Exit the game. The app reports `Game closed`, the worker stops cleanly, and relaunching starts
     a new capture.
  9. No `capture_*.jsonl`, `raw_dump_*.jsonl` or diagnostics log is created by default.
- **Deployed-environment verification:** not applicable (no deploy). The candidate evidence above,
  with the downloaded artifact's commit and the observed results, is the environment verification.
- **Required checks:** `checks`, `tests (ubuntu-latest, 3.11)`, `tests (ubuntu-latest, 3.12)`,
  `tests (windows-latest, 3.12)`, `windows-build`. `audit` is advisory and does not block.
- **Merge order:** single repository, single PR. Close Dependabot #65 as superseded after the
  candidate passes and before the merge.
- **Post-merge:** none required. Nightly refreshes from `main`; the changelog and roadmap are in the
  PR. The next versioned release is a separate task.

## Risks

| Risk | Mitigation |
|---|---|
| A 0.2.x patch re-arms or renames the frame gate, silently starving the overlay again | The T1 tripwire runs the installed SDK's `start_capture()` in CI and fails on the Dependabot PR. |
| The second reading of the graphics mapping fails or races the SDK's reader | `RegionReader` is the SDK's own public reader; a failed open/read is retried and degrades to the log/`is_valid_lap` fallback, never to a crash. The candidate exercises the live path. |
| A clearance line in the current build also carries the `Adding` shape, so it is counted | T2's fixture covers the SDK shapes; the candidate cut+give-back check is the field proof. If it fails, the excerpt defines the build-specific rule. |
| A blanket 15 s penalty dedup would hide a real second cut | Not introduced. The engine keeps `(lap, sector)` folding; T2's two-additions test pins the per-event behaviour. |
| The frame state filter drops valid frames because a build uses an unexpected status value | Unknown/missing status is accepted; only the four documented states are filtered; the candidate drives live, replay and pause. |
| Alternate-layout keys split data for a track the catalog cannot resolve, or old mixed data is wrong for the default layout | Unknown tracks keep the old raw key (no guessing). Old data is never deleted; the default-layout key is unchanged. The limitation is documented in GAME_DATA. |
| The frozen app lacks the catalog JSON, so the alternate-layout suffix silently stops working | `--collect-data acevo` plus `windows-build`, and the candidate check requires the suffixed label on a layout session. |
| The candidate session is skipped | The PR is not merged; the roadmap's field-validation rule is explicit. |
| Reading the region once per poll, not per frame, attributes a cut to a frame up to one poll (100 ms) early | The race-cut pair is a slow state; the log remains the authoritative per-cut signal. |
| `acevo.__version__` reports 0.2.1 for the 0.2.2 package | The app never reads it; `uv.lock` is the version of record. |
