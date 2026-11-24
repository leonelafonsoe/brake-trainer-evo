# Technical Design Specification — dependency batch, November 2026

**Spec branch:** `deps/batch-2026-11-22`
**Base commit:** `f0459cdad85e50a212ebf52a85a4627f7174629d` (`main`, "Merge pull request #76 from
leonelafonsoe/release/0.8.0")
**Repositories:** `brake-trainer-evo` only
**Status:** awaiting GO.

## 1. Objective

Settle the November 2026 dependency queue: six open Dependabot pull requests from the 15 and 22
November runs, plus the one adaptation the batch itself makes necessary.

The queue is in a different state from the October/November batch in
[the previous spec](dependency-maintenance-batch.md): **every pull request is green on all five
required checks.** Nothing is blocked. That changes the job. There is no failing gate to repair;
there is a merge sequence to prove, one upstream semantic change to adopt, and a queue record to
leave behind.

Deliverables:

1. the adapter's live-frame gate learns the **spectated car** rule that `acevo-sdk` 0.2.3 applies to
   its own session manager, with tests that fail on today's code (Task 1);
2. the queue is recorded in the roadmap, and the `## Loop` profile stops claiming that the Security
   audit runs on pull requests, because it does not (Task 2);
3. a documented merge order, with the transient `ruff` hook/lock window and the `uv.lock` rebases
   spelled out (Delivery).

## 2. Non-goals

- **Not a re-lock to latest.** The batch lands exactly the versions the six pull requests propose.
  A blanket `uv lock --upgrade` would move unrelated packages and orphan the open PRs.
- **No `pyproject.toml` change.** `acevo-sdk>=0.2.2,<0.3.0` already admits 0.2.3, and a guard test
  asserts that specifier (`tests/test_release_tools.py:304`). A 0.3.0 move stays a separate,
  reviewed task.
- **No adoption of the SDK's session manager.** The app never imports `SharedSessionManager`; Task 1
  copies its *rule*, not its machinery.
- **No version bump and no release.** 0.8.0 is current; a release is a separate task.
- **No edits to any `dependabot/…` branch.** They are merged as they are, or rebased by Dependabot.
- **New pull requests are out of scope.** Dependabot runs weekly; anything it opens after this spec
  is signed off is a different batch.

## 3. Investigation

### 3.1 The queue as it stands (checked 24 November 2026)

| PR | Package | Change | Files | CI | Mergeable |
|---|---|---|---|---|---|
| #75 | `pre-commit-hooks` | v5.0.0 → **v6.0.0** (major) | `.pre-commit-config.yaml` | green | CLEAN |
| #83 | `acevo-sdk` | 0.2.2 → **0.2.3** (patch) | `uv.lock` | green | CLEAN |
| #77 | `pytest-asyncio` | 1.4.1.post1 → **1.5.0** (minor) | `uv.lock` | green | CLEAN |
| #81 | `ruff` | 0.17.4 → **0.17.6** (patch) | `uv.lock` | green | CLEAN |
| #82 | `ruff-pre-commit` | v0.17.4 → **v0.17.6** (patch) | `.pre-commit-config.yaml` | green | CLEAN |
| #80 | `astral-sh/setup-uv` | 10.3.3 → **10.4.0** (minor) | the four workflows | green | CLEAN |

All six report `checks`, `tests (ubuntu-latest, 3.11)`, `tests (ubuntu-latest, 3.12)`,
`tests (windows-latest, 3.12)` and `windows-build` as successful. `main`'s lock today: `acevo-sdk`
0.2.2, `pytest-asyncio` 1.4.1.post1, `ruff` 0.17.4, `pre-commit-hooks` v5.0.0, `setup-uv` 10.3.3.

### 3.2 What each bump actually changes

- **`pre-commit-hooks` 6.0.0** (release notes): requires Python ≥ 3.9 (irrelevant; the project needs
  3.11+), removes `check-byte-order-marker` and `fix-encoding-pragma`. Neither is configured:
  `.pre-commit-config.yaml` uses `check-yaml`, `check-toml`, `check-merge-conflict`,
  `check-added-large-files`, `end-of-file-fixer` and `trailing-whitespace`, all present in v6. The
  `checks` job runs `pre-commit run --all-files` and is green on #75, which is the direct proof.
- **`acevo-sdk` 0.2.3**: the published wheel differs from 0.2.2 in exactly two files —
  `acevo/__init__.py` (`__version__`, which 0.2.2 wrongly reported as `0.2.1`) and
  `acevo/shared_session.py`, where `_is_replay_graphics_state` now also treats a **spectated car**
  as not-live: `focused_car_id != player_car_id` ⇒ replay. Its only caller is
  `SharedSessionManager` (`acevo/shared_session.py:796`), which this app never imports
  (`grep -rn "SharedSession" src/` is empty). No API, offset or decoder change.
- **`pytest-asyncio` 1.5.0**: adds a `fixture-scope` value for
  `asyncio_default_fixture_loop_scope` and fixes marker validation. The declared `"function"` stays
  valid, and the suite is green under `filterwarnings = ["error"]`.
- **`ruff` 0.17.5/0.17.6**: fixes to `B033`, `F823`, `RUF072`, `SIM208` and friends. No rule change
  turns a new violation on in the selected `E,F,I,UP,B,SIM` set; both `ruff check` and
  `ruff format --check` are green on #81 and #82.
- **`setup-uv` 10.4.0**: a new `require-checksums` input (off by default), PEP 440 specifier fixes,
  and a Windows cached-Python fix. The workflows pass no `version` or `checksum` input, so nothing
  to configure.

**Conclusion:** no bump forces a code or configuration change. The batch's only engineering work is
the semantic drift in §3.3.

### 3.3 The rule the app duplicates, and does not yet have

`telemetry.py:170` gates every frame on `_live_frame`, which accepts only `status == 2` (`AC_LIVE`),
falling back to `status_name`, and assumes live when neither field is present. That covers OFF,
REPLAY, PAUSE and teardown. It does **not** cover a live session while the camera follows another
car: in that state the status is `AC_LIVE`, the position and track are real, and the app would learn
the *spectated* car's braking points under the player's track/car key. The SDK 0.2.3 changelog names
the case and fixes it upstream with `focused_car_id != player_car_id`.

The fields are available to this app: `decode_graphics` publishes `focused_car_id` and
`player_car_id` from the graphics struct (`acevo/decoder.py:958-959, 1122-1123`) in both 0.2.2 and
0.2.3, and `sample_from_frame` already hands the decoded graphics mapping to `_live_frame`
(`telemetry.py:269, 276`). This is the same class of adaptation as "ignore non-live telemetry
frames" in the 0.8.0 batch: adopt the upstream rule in the adapter's own gate instead of importing
a private helper.

### 3.4 Why `audit` shows on some pull requests and not others

`security.yml` triggers on `schedule`, `workflow_dispatch` and `push` with `paths: [uv.lock,
pyproject.toml]`. Pull requests that touch `uv.lock` (#83, #81, #77) get an `audit` check because
the Dependabot branch push matches the path filter; #75, #82 and #80 do not, and neither would any
future pull request that leaves `uv.lock` alone. The check is advisory (it is not one of the five
required jobs), so nothing is blocked — but `AGENTS.md` says the audit "runs on its own schedule and
on pull requests", which is false. Task 2 corrects the profile rather than changing CI: making
`pip-audit` a pull-request check would add a network-dependent advisory job to every PR, and
`docs/DEVELOPMENT.md:86` already documents the real behaviour ("weekly and when dependencies
change").

### 3.5 Why the merge order is not arbitrary

- Three pull requests rewrite different regions of `uv.lock` (#83 at the `acevo-sdk` entry near the
  top, #77 at `pytest-asyncio`, #81 at `ruff`). Each was generated against `main` at a different
  moment, so every merge can leave the next one briefly unmergeable; Dependabot resolves that on
  `@dependabot rebase`. Merging in lock-file order keeps the conflicts predictable.
- #81 (lock) and #82 (hook) propose the same `ruff` 0.17.6 from opposite sides. Whichever lands
  first, the hook and the lock are out of step until the second lands. They must land back-to-back
  so the window is one merge long, and both are green independently in either order.
- #75 (major) first gives every later pull request's `checks` job a run with `pre-commit-hooks` v6,
  which is more exposure than its own green run.
- #80 (workflow action) last means the spec PR — and every later pull request — runs all five jobs
  on `setup-uv` 10.4.0, so the new action is exercised beyond its own branch.

## 4. Constraints

1. `AGENTS.md`: never lower the coverage floor, silence a warning, or delete a test. Task 1 adds
   tests and changes no warning policy.
2. `uv.lock` is only ever updated by `uv`, never by hand, and CI's `uv sync --locked` proves it.
3. A behavioural change needs a `CHANGELOG.md` line under `## Unreleased`, a test, and the owning
   doc page updated.
4. One branch per spec, tasks as commits on it, one pull request.
5. The learned-data format does not change: no `DATA_VERSION` bump, no migration, no settings key.

---

## Task 1 — Adopt the SDK's spectated-car rule in the live-frame gate

**Task ID:** T1
**Depends on:** nothing. Works with `acevo-sdk` 0.2.2 and 0.2.3, so it is independent of #83.

### Outcome

Frames captured while the camera follows another car no longer teach braking points, matching
`acevo-sdk` 0.2.3's own replay/spectate rule. Driver-camera frames, single-player, replays, pauses
and pre-0.2 captures behave exactly as they do today.

### Current behaviour

`_live_frame` (`src/brake_trainer/telemetry.py:170-190`) returns true for `status == 2`
(`AC_LIVE`), then for a `status_name` spelling of live, then assumes live when neither field exists.
`sample_from_frame` (`telemetry.py:267-299`) drops the frame when it returns false. Nothing compares
`focused_car_id` with `player_car_id`, so a live session watched from another car's camera is
accepted and learned.

### File map

| File | Change |
|---|---|
| `src/brake_trainer/telemetry.py` | add a small `_car_id` helper; compare the two ids at the top of `_live_frame` |
| `tests/test_telemetry_audio.py` | three reject cases and two accept cases in the existing parametrizations |
| `docs/GAME_DATA.md` | extend "Frame states" with the spectated-car rule |
| `docs/GUIDE.md` | extend the "Only live driving teaches" sentence |
| `CHANGELOG.md` | one `### Fixed` bullet under `## Unreleased` |
| `docs/plans/deps-batch-2026-11-22.md` | already written; commit it unchanged |

Nothing else. In particular: no settings key, no `DATA_VERSION`/`SETTINGS_VERSION` change, no
`docs/SETTINGS.md` regeneration, no `pyproject.toml` change.

### Design

1. **A type-narrowing helper** next to `_live_frame`:

   ```python
   def _car_id(value: Any) -> int | None:
       """A car slot id from the graphics block, or None when absent or not a real integer."""
       if isinstance(value, int) and not isinstance(value, bool):
           return value
       return None
   ```

   The bool exclusion mirrors the existing rule for `status` (`telemetry.py:178-180`): a bool is not
   an id. The helper keeps `mypy --strict` happy without an `all()` generator that cannot narrow.

2. **The gate** at the top of `_live_frame`, before the status check:

   ```python
   focused, player = _car_id(gfx.get("focused_car_id")), _car_id(gfx.get("player_car_id"))
   if focused is not None and player is not None and focused != player:
       return False
   ```

   Follow the SDK exactly: the comparison only applies when **both** fields are present integers.
   One missing field, a non-integer value, or equal ids leave the existing status logic in charge,
   so builds that do not publish the fields keep working.

3. **Docstring** — extend the existing one rather than adding a second explanation: a live session
   with the camera on another car still carries a position and a track, so it cannot teach either;
   `acevo-sdk` 0.2.3 names the case as `focused_car_id != player_car_id`; the numeric `status` field
   still wins over `status_name`, and a build without either state field is still assumed live when
   the ids agree or are absent.

4. **`docs/GAME_DATA.md`** — extend the "Frame states" paragraph (lines 34-38) with one sentence:
   a live session whose `focused_car_id` differs from `player_car_id` is spectating another car and
   is ignored by the same rule the SDK applies, while equal or missing ids fall back to the status
   field.

5. **`docs/GUIDE.md`** — the sentence at line 207 becomes: "Only live driving teaches: frames from a
   replay, a pause, or a session you are watching from another car's camera are ignored, so none of
   them changes your marks." Three cases need a plural pronoun; do not keep "neither". Keep the rest
   of the paragraph and the link to `GAME_DATA.md` intact.

6. **`CHANGELOG.md`** — new `### Fixed` section directly under `## Unreleased`:

   > Frames captured while the camera follows another car no longer teach braking points. A live
   > session with `focused_car_id` different from `player_car_id` is now ignored, matching the rule
   > `acevo-sdk` 0.2.3 applies to its own session manager. Driver-camera frames and builds that do
   > not publish the fields behave as before.

### Tests

Extend the two existing parametrizations in `tests/test_telemetry_audio.py` — they already build
frames through `_frame_with_state` (`:335`), which merges fields into the graphics block of
`frame()` (`:49`).

**Reject list** (`test_sample_rejects_frames_that_are_not_live`, after `"numeric-status-wins"`):

| Parameters | id |
|---|---|
| `{"status": 2, "status_name": "AC_LIVE", "focused_car_id": 3, "player_car_id": 1}` | `"spectating-a-live-session"` |
| `{"focused_car_id": 3, "player_car_id": 1}` | `"spectating-without-a-status-field"` |
| `{"status": 2, "focused_car_id": 3, "player_car_id": 1}` | `"spectating-numeric-status"` |

**Accept list** (`test_sample_accepts_a_live_frame`, after `"no-status-field"`):

| Parameters | id |
|---|---|
| `{"status": 2, "focused_car_id": 4, "player_car_id": 4}` | `"player-camera"` |
| `{"status": 2, "focused_car_id": 4}` | `"one-id-field-missing"` |

The accept cases are the regression guard for the expensive failure mode: if the comparison ran on
a missing or incomparable field, every frame would be dropped and the app would neither learn nor
update the overlay.

**Required proofs** (report the exact command and output):

1. The new reject cases fail on the unmodified gate. Run them before editing `telemetry.py`:
   ```bash
   uv run pytest -q -W error tests/test_telemetry_audio.py -k "spectating"
   ```
   Expect three failures with `assert None is not None`-style output, then edit.
2. Fast gate:
   ```bash
   uv run ruff format --check . && uv run ruff check . && uv run mypy
   uv run pytest -q -W error tests/test_telemetry_audio.py
   ```
3. Whole suite on the locked environment (no regression):
   ```bash
   uv run pytest -q -W error
   ```

### Acceptance criteria

1. `_live_frame` returns false when both ids are present integers and differ, with `file:line`
   evidence, and the status check still runs when they are equal or absent.
2. The five new cases are in the parametrizations and pass; the two accept cases prove the gate does
   not drop ordinary driver-camera frames.
3. The reject cases were observed failing before the change (proof 1's output in the report).
4. `uv run ruff format --check .`, `uv run ruff check .`, `uv run mypy` and
   `uv run pytest -q -W error` all exit 0.
5. `docs/GAME_DATA.md`, `docs/GUIDE.md` and `CHANGELOG.md` carry the changes described above.
6. `DATA_VERSION`, `SETTINGS_VERSION`, `pyproject.toml` and every file outside the file map are
   untouched.

### Rollback

Revert the commit. There is no stored-format change, so no data migration: nothing is re-read or
rewritten. Marks already learned from a spectated lap before the fix stay in the user's file until
they are deleted from **Settings → Data**; that is a user action, not a rollback step. The only lost
capability is the new rejection itself.

---

## Task 2 — Record the batch, and make the profile tell the truth about the audit

**Task ID:** T2
**Depends on:** nothing. Independent of T1; can be the same PR.

### Outcome

The roadmap's state and queue name the November batch, its versions and where its evidence lives,
so the next reader does not have to reconstruct it from closed pull requests. `AGENTS.md` stops
claiming that the Security audit runs on every pull request.

### Current behaviour

`docs/ROADMAP.md` "State" ends at the 0.8.0 release and "Immediate queue" item 1 records only the 14
November batch. The `## Loop` profile in `AGENTS.md` says the Security workflow "runs on its own
schedule and on pull requests", while `security.yml` has no `pull_request` trigger (§3.4).

### File map

| File | Change |
|---|---|
| `docs/ROADMAP.md` | one bullet in "State"; one paragraph in "Immediate queue" item 1 |
| `AGENTS.md` | the audit sentence in the `## Loop` "Required checks" bullet only |

Nothing else in `AGENTS.md` may change.

### Design

**1. `docs/ROADMAP.md`, "State".** After the 0.8.0 bullet, add this bullet exactly:

```markdown
- **Dependency queue (22 November 2026, checked 24 November 2026):** six Dependabot pull requests
  from the 15 and 22 November runs — `pre-commit-hooks` **6.0.0**, `acevo-sdk` **0.2.3**,
  `pytest-asyncio` **1.5.0**, `ruff` **0.17.6** and its `pre-commit` hook, and
  `astral-sh/setup-uv` **10.4.0**. The batch also adopts the SDK 0.2.3 spectated-car rule in the
  adapter. Evidence and merge order: [the batch spec](plans/deps-batch-2026-11-22.md).
```

The date is explicit because this is transient state, per the page's own rule.

**2. `docs/ROADMAP.md`, "Immediate queue" item 1.** After the 14 November paragraph, add this
paragraph exactly:

```markdown
The 22 November queue is the same shape and needed no repair: all six pull requests were green
before the batch started. It carries one adaptation — the SDK 0.2.3 spectated-car rule now applies
in `telemetry.py` — and the merge order plus the `ruff` hook/lock window are in
[the batch spec](plans/deps-batch-2026-11-22.md).
```

Both blocks are shown fenced because this spec lives under `docs/plans/`: the same relative link
written here would resolve to `docs/plans/plans/…` and break `tests/test_docs_links.py`. The
roadmap entry itself carries a real Markdown link, since `docs/ROADMAP.md` sits one level higher.

**3. `AGENTS.md`, `## Loop` → "Required checks".** Replace "runs on its own schedule and on pull
requests" with "runs on its own schedule and on pushes that change `uv.lock` or `pyproject.toml`",
and keep "it is advisory for merge purposes". Add "and may not appear on a pull request at all" so
nobody waits for a check that cannot run.

This is a profile correction, not a CI change: `docs/DEVELOPMENT.md:86` already documents the real
triggers, and the audit stays advisory.

### Tests

No new automated test: both files are prose. `tests/test_release_tools.py` has no assertion about
the audit trigger or the roadmap text, and adding one would pin wording that is meant to be edited.

**Required proofs:**

```bash
uv run pre-commit run --all-files          # check-yaml / end-of-file-fixer / trailing-whitespace
uv run ruff format --check . && uv run ruff check . && uv run mypy
```

`AGENTS.md` and `docs/ROADMAP.md` are not Python; the point of the gate here is that nothing else
moved.

### Acceptance criteria

1. The "State" bullet and the queue paragraph are present with the six versions and a link to this
   spec, and the check date is stated.
2. The `## Loop` audit sentence matches `security.yml`'s triggers and keeps "advisory".
3. No other line of `AGENTS.md` changed; no other file changed.
4. The fast gate exits 0.

### Rollback

Revert the commit. Documentation only; no build, test or runtime behaviour depends on it.

---

## 5. Delivery

### 5.1 Repositories and branches

| Repository | Spec branch | PR |
|---|---|---|
| `brake-trainer-evo` | `deps/batch-2026-11-22`, created from `main` at `f0459cd` | one PR carrying T1 and T2 as two commits |

Tasks are commits on that branch, never separate branches. The six Dependabot pull requests keep
their own branches and are never edited.

### 5.2 Deploy, candidate and environment

**No deploy, no staging, no deployed environment.** Nothing is deployed from a PR; the profile has
no host, no container and no URL, so the deployed-environment pass is **not applicable** and there
is no "unverifiable" gap to record.

**Candidate step: applicable to the spec PR only.** Task 1 changes what the app learns, which only
the packaged build can prove. From the spec PR's `windows-build` artifact:

1. **Normal driving** (the regression check): run a session on any track; the overlay must update
   and a sector must still be learned. This is the proof that the id comparison does not reject
   ordinary frames — accept case `player-camera` in the unit tests is the cheap version of it.
2. **Spectating**: bring up a session where the camera follows another car, drive a few corners'
   worth of frames, and confirm no new mark appears for that sector in **Settings → Data**.
3. Record the artifact name and the outcome of both checks in the delivery report.

The six Dependabot PRs need no candidate step: none of them changes shipped behaviour. `acevo-sdk`
0.2.3's only semantic change lives in `SharedSessionManager`, which the app does not import (§3.2).
If any of them is exercised anyway, say so; if the candidate step is skipped, the report says it was
skipped.

### 5.3 Required checks

All five jobs must pass on the spec PR, on every Dependabot PR, and again on the spec PR after its
final rebase:

- `checks`
- `tests (ubuntu-latest, 3.11)`
- `tests (ubuntu-latest, 3.12)`
- `tests (windows-latest, 3.12)`
- `windows-build`

The Security `audit` job is advisory, appears only when `uv.lock`/`pyproject.toml` changed, and
never blocks.

### 5.4 Merge order

Merge one pull request at a time, wait for the required checks on each, and re-read the version in
`main`'s `uv.lock` after every merge: Dependabot re-resolves on rebase, so the merged version can
differ from the one in the diff.

| # | PR | What lands | Why here |
|---|---|---|---|
| 1 | #75 | `pre-commit-hooks` v6.0.0 | Major bump; every later PR's `checks` job then runs v6 |
| 2 | #83 | `acevo-sdk` 0.2.3 | Lock-file order, top entry first; the version Task 1 documents |
| 3 | #77 | `pytest-asyncio` 1.5.0 | Lock-file order; verify the suite is still green with the declared loop scope |
| 4 | #81 | `ruff` 0.17.6 in `uv.lock` | Opens the hook/lock window |
| 5 | #82 | `ruff` v0.17.6 hook | Closes it one merge later; the two must be back to back |
| 6 | #80 | `setup-uv` 10.4.0 | Workflow-only; the next PR then runs all five jobs on it |
| 7 | spec PR | T1 + T2 | Rebased on the updated `main`; its CI and candidate run on the final tree |

Rules:

- Never hand-edit a `dependabot/…` branch. If a PR cannot merge, comment `@dependabot rebase` and
  wait for a green run; if it goes red for a reason not explained by this spec, stop and report.
- If two lock-file PRs conflict, rebase the later one; never resolve `uv.lock` by hand.
- If a version in `main` after a merge is not the one this spec names, stop and report before
  merging the next.

### 5.5 Post-merge

None required. A push to `main` refreshes Nightly automatically; there is no submodule, pointer or
release-notes step. The roadmap's dated queue paragraph may be closed out in a follow-up docs
change after step 7 — deliberately not inside this spec.

## 6. Risks and what will not be tested

| Risk | Mitigation |
|---|---|
| The id comparison rejects every frame on a build that reports the two ids inconsistently (overlay freezes, nothing is learned) | It is the expensive failure mode, so it has two accept tests and is the first candidate check; rollback is one revert. Upstream applies the same rule in the field. |
| Frames from a legitimately driven car are dropped in multiplayer | The player's own slot is `player_car_id`; the camera defaults to it. Candidate check 1 covers normal driving. |
| `pre-commit-hooks` v6 behaves differently for a file added later | All six configured hooks are present in v6 and green on #75; the `checks` job runs them on every PR. |
| `uv.lock` churn between #83/#77/#81 | Merge order keeps the entries separate; `@dependabot rebase` is the only repair, and CI's `--locked` sync proves the result. |
| `pytest-asyncio` 1.5.0 interacts with `filterwarnings = ["error"]` | Green on #77 and locally; the declared fixture loop scope is unchanged. |
| `setup-uv` 10.4.0 changes caching on the Windows leg | Green on #80, and the spec PR (last) runs `windows-build` on it. |
| A Dependabot run opens new PRs mid-delivery | Out of scope; they are another batch. |

**Not tested by this spec, and to be reported as such:** the in-game candidate check unless the
maintainer runs it; the Windows-only test leg and packaged build (CI's authority); whether
spectating another car would have taught wrong marks before the fix (it is inferred from the SDK
changelog and the frame contents, not reproduced here).
