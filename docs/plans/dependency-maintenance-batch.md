# Technical Design Specification — dependency maintenance batch

**Spec branch:** `deps/maintenance-batch`
**Base commit:** `dbb6da9` (`main`, "docs: record the post-0.7.0 state and next queue")
**Repositories:** `brake-trainer-evo` only
**Status:** approved; T1 and T2 delivered on this branch.

## 1. Objective

Settle the weekly dependency queue by unblocking the one red Dependabot pull request and landing the
green ones, without weakening any gate.

The queue on 14 November 2026 is seven open Dependabot pull requests. Six pass CI. One — **#63,
`pytest` 9.1.1 → 9.2.0** — fails on all three test legs. That failure is not a test failure: pytest
dies during start-up, before a single test is collected, so nothing about the suite is actually
known to be broken. This spec removes that cause with a configuration change and then delivers the
merge sequence.

Deliverables:

1. a code/config change on `deps/maintenance-batch` that lets pytest 9.2.0 start the suite, plus a
   guard that the change is not quietly deleted later (Task 1);
2. the `ruff` version that pre-commit runs brought back into step with the locked one, and placed
   under Dependabot's care so it cannot drift again (Task 2);
3. a documented merge order for the six Dependabot pull requests (Delivery).

## 2. Non-goals

- **PR #65 (`acevo-sdk` 0.1.1 → 0.2.1) is out of scope.** `docs/ROADMAP.md` assigns it to a
  separate field-validation task: 0.2 changes log parsing, lap authority and validity handling, and
  CI cannot prove that live frames are not withheld. It must not be merged as part of a mechanical
  dependency batch.
- **The `ignore: ["0.2.x"]` rule in `.github/dependabot.yml` is out of scope.** The roadmap makes
  fixing that range part of the `acevo-sdk` task, not this one.
- **No version bump, no release, no tag.** `0.7.1` stays a separate task.
- **Not a re-lock to latest.** The batch lands the versions the open pull requests propose. A
  blanket `uv lock --upgrade` would move `pytest-asyncio` to 1.5.0 and `ruff` to 0.17.5 and orphan
  the open PRs; that is a different, unrequested change.
- **No change to `filterwarnings`.** See "Why the answer is not `filterwarnings`" below.

## 3. Investigation

### 3.1 Why #63 fails

All three test legs fail in the **gates** step, two seconds after start-up
([CI run 41363131578](https://github.com/leonelafonsoe/brake-trainer-evo/actions/runs/41363131578)).
The log ends with:

```text
INTERNALERROR>   File ".../pytest_asyncio/plugin.py", line 299, in pytest_configure
INTERNALERROR>     warnings.warn(PytestDeprecationWarning(_DEFAULT_FIXTURE_LOOP_SCOPE_UNSET))
INTERNALERROR> pytest.PytestDeprecationWarning: The configuration option
                 "asyncio_default_fixture_loop_scope" is unset.
INTERNALERROR> The event loop scope for asynchronous fixtures will default to the "fixture" caching
                 scope. Future versions of pytest-asyncio will default the loop scope for
                 asynchronous fixtures to "function" scope. Set the default fixture loop scope
                 explicitly in order to avoid unexpected behavior in the future.
##[error]Process completed with exit code 3.
```

The chain:

1. `pyproject.toml` sets `filterwarnings = ["error"]`, so any warning is an error (by design; see
   `docs/DEVELOPMENT.md`, "Warnings are errors").
2. `pytest-asyncio` warns from `pytest_configure` when `asyncio_default_fixture_loop_scope` is unset.
3. pytest **9.2.0** applies the ini `filterwarnings` early enough that a warn raised during
   `pytest_configure` is caught and promoted to an exception. 9.1.1 did not, which is why the same
   tree has been green since the setting was introduced.
4. An exception in `pytest_configure` aborts the run with `INTERNALERROR` and exit code 3.

### 3.2 Evidence collected for this spec

Reproduced in a throwaway clone at `dbb6da9`, Python 3.12.3 and 3.11.17, `QT_QPA_PLATFORM=offscreen`:

| Configuration | Result |
|---|---|
| pytest 9.1.1, `filterwarnings = ["error"]`, no key (today's `main`) | 521 passed, 4 skipped |
| pytest 9.2.0, `filterwarnings = ["error"]`, no key | `INTERNALERROR`, exit 3 — matches CI byte for byte |
| pytest 9.2.0, `filterwarnings = ["default"]`, no key | 521 passed, 4 skipped |
| pytest 9.2.0 + `pytest-asyncio` 1.4.1, no key | still `INTERNALERROR` — so #66 does **not** fix it |
| pytest 9.2.0, `asyncio_default_fixture_loop_scope = "function"` | 521 passed, 4 skipped (3.11 and 3.12) |
| pytest 9.1.1, key present | 521 passed, 4 skipped — no regression on the current pin |

Whole batch together (`pytest` 9.2.0, `pytest-asyncio` 1.4.1, `ruff` 0.17.3, `mypy` 2.4.1, plus the
key): `pre-commit run --all-files`, `ruff format --check`, `ruff check`, `mypy`,
`mypy --platform win32`, `gen_settings_doc.py --check`, `pytest -q -W error` and
`pytest -q -W error --cov` (`88.44%`, floor `84.0`) all exit 0.

### 3.3 Why `"function"`, and why it is safe here

- It is the value `pytest-asyncio` documents as the future default, so declaring it now removes the
  warning instead of deferring the migration.
- It is inert for this repository: every fixture under `tests/` is a plain synchronous
  `@pytest.fixture`, and there are no `async def` fixtures (`tests/conftest.py:101-141` and the
  module-level fixtures are all sync). Fixture loop scope therefore has nothing to govern.
- The async tests (`tests/test_telemetry_audio.py`, `tests/test_gamelog_tail.py`) are async *test
  functions*, governed by `asyncio_default_test_loop_scope`, which already defaults to `function`
  and is unaffected.

### 3.4 What each open PR actually changes

| PR | Package | Files touched | CI |
|---|---|---|---|
| #61 | `astral-sh/setup-uv` 10.3.2 → 10.3.3 | 4 workflow files (SHA + comment) | pass |
| #62 | `ruff` 0.17.2 → 0.17.3 | `uv.lock` only | pass |
| #63 | `pytest` 9.1.1 → 9.2.0 | `uv.lock` only | **fails** |
| #64 | `mypy` 2.4.0 → 2.4.1 | `uv.lock` only | pass |
| #65 | `acevo-sdk` 0.1.1 → 0.2.1 | `pyproject.toml`, `uv.lock` | pass — **out of scope** |
| #66 | `pytest-asyncio` 1.4.0 → 1.4.1 | `uv.lock` only | pass |
| #67 | `softprops/action-gh-release` 3.0.3 → 3.0.4 | 2 workflow files (SHA + comment) | pass |

No PR touches `pyproject.toml` except #65, so Tasks 1 and 2 cannot conflict with any of them.

### 3.5 The drift nobody is watching

`.pre-commit-config.yaml:23` pins `astral-sh/ruff-pre-commit` at `rev: v0.17.2`, matching the
`ruff` in `uv.lock` today. `.github/dependabot.yml` configures only the `uv` and `github-actions`
ecosystems. `.pre-commit-config.yaml` is therefore unmanaged: after #62 lands, the hook runs ruff
0.17.2 while `uv run ruff` runs 0.17.3, and the two would separate further every week. The tag
`v0.17.3` exists in `astral-sh/ruff-pre-commit` (`25bcf950…`), and
`pre-commit run --all-files` on `main`'s tree passes with it.

## 4. Constraints

1. `AGENTS.md` forbids lowering the coverage floor, silencing a warning globally, and deleting a
   test to make a change pass. §4.3 follows from this.
2. `uv.lock` is updated with the project (`uv lock` / `uv add`), never by hand.
3. Every change needs a `CHANGELOG.md` line under `## Unreleased` and the affected doc page updated.
4. A warning is an error. The fix is the cause, not the filter.

### Why the answer is not `filterwarnings`

Adding an ignore for `PytestDeprecationWarning`, or dropping `"error"`, would turn the whole warning
policy off to hide one message. `docs/DEVELOPMENT.md` says exactly this: "Fix the cause; do not
filter it away unless a dependency cannot be fixed." The dependency *can* be fixed by declaring the
setting, and it costs one line. Rejected.

---

## Task 1 — Declare the asyncio fixture loop scope

**Task ID:** T1
**Depends on:** nothing. Must be merged before #63.

### Outcome

`pytest` 9.2.0 can start the suite, so #63 turns green on rebase. The setting cannot be silently
deleted later, because a test fails if it is.

### Current behaviour

`pyproject.toml` `[tool.pytest.ini_options]` declares `asyncio_mode = "auto"` and
`filterwarnings = ["error"]` but leaves `asyncio_default_fixture_loop_scope` unset. On pytest 9.2.0
that combination aborts the run in `pytest_configure` with `INTERNALERROR` and exit code 3 (§3.1).

### File map

| File | Change |
|---|---|
| `pyproject.toml` | add `asyncio_default_fixture_loop_scope = "function"` to `[tool.pytest.ini_options]`, immediately after `asyncio_mode` |
| `tests/test_release_tools.py` | add one guard test, next to the existing pyproject-configuration tests |
| `docs/DEVELOPMENT.md` | one short note under the "Warnings are errors" bullet |
| `CHANGELOG.md` | one bullet under `## Unreleased` |

Nothing else. `uv.lock` must not change in this task.

### Design

1. **`pyproject.toml`** — one line, no reformatting of the surrounding block:

   ```toml
   [tool.pytest.ini_options]
   testpaths = ["tests"]
   asyncio_mode = "auto"
   asyncio_default_fixture_loop_scope = "function"
   pythonpath = ["src"]
   ```

   Add a brief comment only if the existing file has comments in this block; it currently does not,
   so the *why* lives in `docs/DEVELOPMENT.md` and in the guard test's docstring instead of as a
   TOML comment.

2. **Guard test** in `tests/test_release_tools.py`, matching the existing `tomllib` style
   (`tests/test_release_tools.py:331-350`):

   ```python
   def test_pytest_declares_the_asyncio_fixture_loop_scope():
       """pytest 9.2 promotes a configure-time warning to an error, so the scope must be set.

       pytest-asyncio warns from ``pytest_configure`` when this key is unset. With
       ``filterwarnings = ["error"]`` that warning aborted the whole run with INTERNALERROR
       before collection. Do not remove the setting: silence is what breaks CI.
       """
       import tomllib

       config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

       scope = config["tool"]["pytest"]["ini_options"].get("asyncio_default_fixture_loop_scope")

       assert scope in {"function", "class", "module", "package", "session"}
   ```

   `import tomllib` stays inside the function, as the neighbouring tests do.

3. **`docs/DEVELOPMENT.md`** — extend the existing "Warnings are errors." bullet (do not add a new
   section):

   > `asyncio_default_fixture_loop_scope` is declared in `pyproject.toml` for this reason:
   > `pytest-asyncio` warns when it is unset, and from pytest 9.2 that configure-time warning is an
   > error that stops the run before collection.

4. **`CHANGELOG.md`** — under `## Unreleased`, in the existing `### Changed` section:

   > Pinned the pytest-asyncio fixture loop scope explicitly (`asyncio_default_fixture_loop_scope =
   > "function"`). pytest 9.2 turns the "loop scope is unset" deprecation into a start-up error
   > under `filterwarnings = ["error"]`, which stopped the suite from running at all. No behaviour
   > change: every test fixture is synchronous.

### Tests

The guard test above, plus the existing suite run under the new configuration.

**Required proofs** (report the exact command and output for each):

1. Current lock, full suite green — no regression:
   ```bash
   uv run ruff format --check . && uv run ruff check . && uv run mypy
   uv run pytest -q -W error
   ```
   Expect `521 passed, 4 skipped` (count may be 522 once the guard test is added).

2. The actual failure is fixed, with the tree left clean:
   ```bash
   uv pip install 'pytest==9.2.0'          # temporary, untracked
   uv run --no-sync python -c "import pytest; print(pytest.__version__)"   # expect 9.2.0
   uv run --no-sync pytest -q -W error                                     # expect all passed
   uv sync --locked --extra dev            # restore the locked 9.1.1
   uv run --no-sync python -c "import pytest; print(pytest.__version__)"   # expect 9.1.1
   git status --porcelain                  # must show no uv.lock change
   ```
   **Assert the version and the pass count.** A run that reports `no tests ran` is a failed proof,
   not a pass. Do not use `uv run --with pytest==9.2.0`: it mutates `.venv` in place and can leave a
   half-synced environment.

3. The guard bites:
   ```bash
   # remove the line from pyproject.toml, run the guard test, confirm it fails, restore the line
   uv run pytest -q -W error tests/test_release_tools.py -k asyncio_fixture_loop_scope
   ```

### Acceptance criteria

1. `pyproject.toml` declares `asyncio_default_fixture_loop_scope = "function"` in
   `[tool.pytest.ini_options]`, and nothing else in that block changed.
2. `uv run pytest -q -W error` passes on the current lock with pytest 9.1.1.
3. `uv run pytest -q -W error` passes with pytest 9.2.0, and the version was asserted before the
   run (proof 2).
4. `git status --porcelain` shows no `uv.lock` change at the end of the task.
5. The guard test passes, and was observed failing when the setting is removed.
6. `uv run mypy` and `uv run mypy --platform win32` pass (the test tree is type-checked).
7. `docs/DEVELOPMENT.md` carries the note; `CHANGELOG.md` has the bullet under `## Unreleased`.
8. No file outside the file map is touched.

### Rollback

Revert the commit. If #63 has already been merged, revert it in the same action or pin `pytest` back
below 9.2 in the same commit — otherwise CI returns to the `INTERNALERROR`. Removing the line alone,
with 9.2.0 locked, breaks `checks` and `tests` for every later pull request. There is no runtime
surface: no user data, no schema, no settings, no `DATA_VERSION`/`SETTINGS_VERSION` change.

---

## Task 2 — Keep the pre-commit ruff in step, and under Dependabot

**Task ID:** T2
**Depends on:** nothing. Independent of T1 and of every open PR.

### Outcome

The ruff that `pre-commit run --all-files` executes is brought forward to `v0.17.3`, the version
Dependabot PR #62 pins for the project, and a weekly Dependabot pull request maintains the hook from
now on instead of leaving it unmanaged. The hook and the lock converge when #62 merges; until then
the hook is one patch ahead, which is a strict improvement over drifting permanently apart.

### Current behaviour

`.pre-commit-config.yaml:23` pins `astral-sh/ruff-pre-commit` at `v0.17.2`; `uv.lock` pins
`ruff` 0.17.2, so they agree today. `.github/dependabot.yml` manages the `uv` and `github-actions`
ecosystems only. Merging #62 without this task leaves the hook on 0.17.2 and the CLI on 0.17.3, and
nothing would ever raise the hook version again.

### File map

| File | Change |
|---|---|
| `.pre-commit-config.yaml` | `rev: v0.17.2` → `rev: v0.17.3` |
| `.github/dependabot.yml` | add a `pre-commit` ecosystem entry |
| `CHANGELOG.md` | one bullet under `## Unreleased` |

### Design

1. **`.pre-commit-config.yaml`** — bump the single `rev` on line 23. Change nothing else; the hook
   ids, the `--fix` argument and the local `mypy` hook stay as they are.

2. **`.github/dependabot.yml`** — add a third block, matching the shape of the existing ones:

   ```yaml
     - package-ecosystem: pre-commit
       directory: /
       schedule:
         interval: weekly
       open-pull-requests-limit: 5
   ```

   Leave the `uv` block, its `acevo-sdk` `ignore` rule, and the `github-actions` block untouched —
   the ignore-range fix belongs to the `acevo-sdk` task.

3. **`CHANGELOG.md`** — under `## Unreleased`:

   > `pre-commit` now runs `ruff` v0.17.3, a patch ahead of the pinned lock until the dependabot bump
   > lands, and Dependabot watches `.pre-commit-config.yaml` so the hook and the project cannot drift
   > apart again.

   The wording must stay true at merge time: this PR lands before #62, so the hook is ahead of
   `uv.lock` for the intervening merges. Do not claim the two are equal yet.

### Tests

No new test. The proof is that the gate which consumes the file still passes with the new rev, and
that the YAML still parses:

```bash
uv run pre-commit run --all-files          # the ruff hooks now run 0.17.3
uv run pre-commit run check-yaml --all-files
```

Report both, and confirm `pre-commit` reports `ruff check` and `ruff format` as Passed rather than
Skipped.

**Deliberately not added:** a test asserting that the hook `rev` equals the locked `ruff` version.
It would fail in the window between Dependabot opening the `uv` bump and the `pre-commit` bump,
blocking two otherwise-correct pull requests. The drift it would catch is now Dependabot's job.

### Acceptance criteria

1. `.pre-commit-config.yaml` has `rev: v0.17.3` on the `ruff-pre-commit` repository and no other
   line in the file changed.
2. `.github/dependabot.yml` has exactly three ecosystem entries (`uv`, `github-actions`,
   `pre-commit`), and the `uv` entry — including the `acevo-sdk` `ignore` rule — is byte-for-byte
   unchanged.
3. `uv run pre-commit run --all-files` exits 0 with `ruff check` and `ruff format` passing.
4. `check-yaml` passes on `.github/dependabot.yml`.
5. The `CHANGELOG.md` bullet is present under `## Unreleased`.
6. No file outside the file map is touched.

### Rollback

Revert the commit. The two versions drift back to whatever `uv.lock` says; no build, test or runtime
behaviour depends on the hook revision, because `pre-commit` is a local convenience wrapper around
the same gates CI runs directly.

---

## 5. Delivery

### 5.1 Repositories and branches

| Repository | Spec branch | PR |
|---|---|---|
| `brake-trainer-evo` | `deps/maintenance-batch`, created from `main` at `dbb6da9` | one PR, carrying T1 and T2 as two commits |

Tasks are commits on that branch, never separate branches. One pull request for the spec.

### 5.2 Deploy

**No deploy and no candidate step.** Nothing in this spec changes shipped behaviour: one pytest
configuration key, one pre-commit hook revision, one Dependabot ecosystem entry. The PR's
`windows-build` artifact is still produced by CI, but there is nothing to exercise in-game, so the
candidate step is recorded as **not applicable** rather than skipped-after-attempt.

### 5.3 Required checks

All five CI jobs must pass before merge:

- `checks`
- `tests (ubuntu-latest, 3.11)`
- `tests (ubuntu-latest, 3.12)`
- `tests (windows-latest, 3.12)`
- `windows-build`

The Security workflow's `audit` job is advisory and does not block.

### 5.4 Merge order

1. **This PR** (`deps/maintenance-batch`). It must be first: #63 stays red until the setting is on
   `main`, because Dependabot rebases onto `main`, not onto our branch.
2. **#63** — `pytest` 9.1.1 → 9.2.0. Clean rebase right after step 1, since neither touches the
   same region of `uv.lock`. This is the step that proves the fix.
3. **#66** — `pytest-asyncio` 1.4.0 → 1.4.1. Its entry sits immediately after `pytest` in
   `uv.lock`, so expect a conflict after step 2; comment `@dependabot rebase` and wait for a green
   run.
4. **#64** — `mypy` 2.4.0 → 2.4.1.
5. **#62** — `ruff` 0.17.2 → 0.17.3. After this the hook and the CLI agree at 0.17.3, as designed
   in T2.
6. **#61** — `astral-sh/setup-uv` 10.3.2 → 10.3.3. Workflow files only; cannot conflict with
   `uv.lock`.
7. **#67** — `softprops/action-gh-release` 3.0.3 → 3.0.4. Workflow files only.

Rules for the sequence:

- Merge one at a time and wait for the required checks on each. Never batch-merge.
- Never edit a `dependabot/…` branch by hand. If a PR cannot merge, ask Dependabot to rebase.
- If any dependency PR goes red for a reason not explained by this spec, stop and report — do not
  force it through.
- **#65 is not merged.** It stays open for the `acevo-sdk` field-validation task.

### 5.5 Post-merge

None required. A push to `main` refreshes Nightly automatically. No submodule or pointer bump.
`docs/ROADMAP.md` "Immediate queue" should be updated to drop the settled rows — as a follow-up
docs change, not inside this spec.

## 6. Risks and what will not be tested

| Risk | Mitigation |
|---|---|
| pytest 9.2.0 breaks a test **on Windows only** | Cannot be reproduced here; the `tests (windows-latest, 3.12)` leg is the authority and must be green before #63 merges. |
| A second 9.2.0 incompatibility appears after the setting is fixed | The whole batch was run end to end locally on 3.11 and 3.12 (gates + coverage); the Windows leg remains the residual gap. |
| Declaring `"function"` changes fixture semantics | No fixture in `tests/` is asynchronous, so nothing is governed by fixture loop scope. Stated in §3.3 and covered by the unchanged suite. |
| The guard test is deleted later "because the warning is gone" | The docstring and the `docs/DEVELOPMENT.md` note both state that removing it is what breaks CI. |
| New Dependabot `pre-commit` ecosystem produces noisy PRs | Accepted deliberately; limit 5, weekly, same cadence as the others. It covers `pre-commit-hooks` too. |
| `uv.lock` conflict churn across steps 2-5 | Expected and handled by `@dependabot rebase`; the merge order puts the two adjacent entries (#63, #66) one after the other. |
| A lock file is edited by hand to resolve a conflict | Forbidden: regenerate with `uv lock`, and let CI's `--locked` sync prove it. |

**Not tested, and to be reported as such:** the Windows test leg, the packaged Windows build, and
anything in-game. There is no user-facing behaviour in this spec, so the in-game candidate step is
not applicable.
