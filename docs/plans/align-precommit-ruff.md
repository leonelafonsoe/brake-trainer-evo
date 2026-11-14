# Technical Design Specification — align the pre-commit ruff rev

**Spec branch:** `deps/align-precommit-ruff`
**Base commit:** `114195a` (`main`, "Merge pull request #67 …")
**Repository:** `brake-trainer-evo`
**Status:** approved; T1 delivered on this branch.

## Objective

Close the one-patch gap between the ruff that `pre-commit` runs and the ruff pinned in `uv.lock`, and
make the shipped CHANGELOG statement true again.

## Background

The dependency batch (`docs/plans/dependency-maintenance-batch.md`, merged in PR #69) pinned
`.pre-commit-config.yaml` to `ruff-pre-commit` `v0.17.3` and added a `pre-commit` Dependabot
ecosystem. Dependabot PR #62 was then rebased with `@dependabot rebase`, which **re-resolved the
dependency to the newest allowed patch** rather than keeping the version in its original diff: it
merged as `bump ruff from 0.17.2 to 0.17.4`.

Result on `main` at `114195a`:

- `uv.lock` pins `ruff` **0.17.4**.
- `.pre-commit-config.yaml` pins `ruff-pre-commit` **v0.17.3**.

So `pre-commit run --all-files` executes ruff 0.17.3 while CI's `ruff format --check .` / `ruff check .`
execute 0.17.4 — the split the batch set out to remove.

The CHANGELOG bullet from that batch also now reads the wrong way round: it says the hook runs
`v0.17.3`, "a patch ahead of the pinned lock", when the hook is in fact a patch behind.

Verified: `.pre-commit-config.yaml` at `rev: v0.17.4` with `uv.lock` at 0.17.4 passes
`pre-commit run --all-files` (exit 0, all 9 hooks Passed, no file rewritten tied to formatting).

## Non-goals

- No dependency re-lock. `uv.lock` must not change.
- No change to the `pre-commit` Dependabot ecosystem, the `acevo-sdk` ignore rule, or any other hook
  (`pre-commit-hooks` stays `v5.0.0`).
- No version bump and no release.

---

## Task 1 — Pin the hook to the locked ruff and correct the changelog

**Task ID:** T1
**Depends on:** nothing.

### Outcome

`pre-commit` and the project CLI run the same ruff (0.17.4), and `CHANGELOG.md` states that
truthfully.

### Current behaviour

`.pre-commit-config.yaml:23` is `rev: v0.17.3`; `uv.lock` pins ruff 0.17.4. `CHANGELOG.md` asserts the
hook is ahead of the lock at `v0.17.3`.

### File map

| File | Change |
|---|---|
| `.pre-commit-config.yaml` | `rev: v0.17.3` → `rev: v0.17.4` |
| `CHANGELOG.md` | replace the "patch ahead of the pinned lock" bullet with a true one |

Nothing else.

### Design

1. **`.pre-commit-config.yaml`** — one line, the `ruff-pre-commit` `rev` on line 23. The tag `v0.17.4`
   exists in `astral-sh/ruff-pre-commit` (`c0f278f1254ccc8fb09676bcdb8d847e7db493e5`). Change nothing
   else in the file: not the `pre-commit-hooks` rev at line 9, not the hook ids, not the `--fix`
   argument, not the local `mypy` hook.

2. **`CHANGELOG.md`** — under `## Unreleased` → `### Changed`, replace the existing bullet:

   > `pre-commit` now runs `ruff` v0.17.3, a patch ahead of the pinned lock until the dependabot bump
   > lands, and Dependabot watches `.pre-commit-config.yaml` so the hook and the project cannot drift
   > apart again.

   with:

   > The `pre-commit` `ruff` hook is back in step with the pinned lock at `v0.17.4`, and Dependabot
   > now watches `.pre-commit-config.yaml`.

   The replacement must not claim the two can never diverge again — they are separate ecosystems and
   did diverge once. State the current fact and the new watch, nothing more.

### Tests

No new test. The gate that consumes the file is the proof.

Required proofs, each reported with its exact command and result:

1. `uv run pre-commit run --all-files` → exit 0, with `ruff check` and `ruff format` reported
   **Passed** (not Skipped).
2. Confirm the hook really runs 0.17.4, not a cached 0.17.3: inspect the hook environment under
   `~/.cache/pre-commit/` (or a fresh `PRE_COMMIT_HOME`) and report the `ruff --version` it contains.
3. `uv run ruff format --check .` and `uv run ruff check .` → exit 0.
4. `uv run pytest -q -W error` → 522 passed, 4 skipped (unchanged).
5. `git status --porcelain --untracked-files=all` → exactly the two mapped files.
6. `uv run python scripts/gen_settings_doc.py --check` → exit 0.

### Acceptance criteria

1. `.pre-commit-config.yaml` has `rev: v0.17.4` on the `ruff-pre-commit` entry; `pre-commit-hooks`
   is still `v5.0.0`; no other line changed.
2. The hook environment reports `ruff 0.17.4`.
3. The CHANGELOG bullet is present under `## Unreleased` → `### Changed` and makes no claim that hook
   and lock can never diverge; it states the current alignment and the Dependabot watch.
4. `uv.lock` is unchanged (`git status --porcelain uv.lock` empty).
5. The full gate passes: `pre-commit --all-files`, `ruff format --check`, `ruff check`,
   `mypy`, `mypy --platform win32`, `pytest -q -W error`, `pytest -q -W error --cov`,
   `gen_settings_doc.py --check`.
6. No file outside the file map is touched.

### Rollback

Revert the commit. The rev returns to `v0.17.3` and the hook is one patch behind the lock again —
the exact state `main` is in today. No runtime, data or schema surface.

---

## Delivery

- **Repository:** `brake-trainer-evo` only.
- **Branch:** `deps/align-precommit-ruff`, one PR.
- **Deploy / candidate:** none required. The change cannot affect the built application; no in-game or
  artifact check applies, and the report says so.
- **Required checks:** `checks`, `tests (ubuntu-latest, 3.11)`, `tests (ubuntu-latest, 3.12)`,
  `tests (windows-latest, 3.12)`, `windows-build`. `audit` is advisory.
- **Merge order:** single PR, merge after required checks pass.
- **Post-merge:** none. Nightly refreshes automatically.

## Risks

| Risk | Mitigation |
|---|---|
| Dependabot re-resolves again on a later rebase and reopens the gap | Accepted: the `pre-commit` ecosystem now watches the file, which is what closes it next time. |
| A `v0.17.4` formatting rule differs from 0.17.3 and reformats the tree | `ruff format --check` and `pre-commit --all-files` both run in the gate; the local probe showed no reformat. |
| The CHANGELOG line is edited in a way that re-introduces an unprovable claim | Acceptance criterion 3 states the required content. |
