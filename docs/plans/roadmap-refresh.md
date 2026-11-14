# Technical Design Specification — refresh the roadmap after the dependency batch

**Spec branch:** `docs/roadmap-refresh`
**Base commit:** `4b087ce` (`main`, "Merge pull request #70 …")
**Repository:** `brake-trainer-evo`
**Status:** approved; T1 delivered on this branch.

## Objective

Bring `docs/ROADMAP.md` back in line with what is actually on `main` after the dependency batch
(PR #69) and the ruff alignment (PR #70).

## Background

`docs/ROADMAP.md` opens by stating its own rule: *"Transient PR state is noted with the date it was
checked and is removed when handled."* The 14 November 2026 batch is now handled, so its rows should
be gone. Instead the page still records a state that no longer exists:

- `"No open code PRs. Seven weekly Dependabot PRs are open"` (`ROADMAP.md:15`) — six of the seven
  merged; only **#65** is open.
- The dependency table (`ROADMAP.md:44-52`) lists `#62 | ruff 0.17.2 → 0.17.3` and
  `#63 | pytest 9.1.1 → 9.2.0 | **fails**`. Both merged, and #62 actually landed as **0.17.4**:
  Dependabot re-resolved to the newest allowed patch when the PR was rebased, so the merged version
  differs from the one in the PR's diff.
- `"keep #63 open until the failing leg is understood and fixed"` (`ROADMAP.md:54`) — done.

`§5.5` of `docs/plans/dependency-maintenance-batch.md` explicitly deferred this cleanup to a
follow-up docs change. This is that change.

## Non-goals

- No code, configuration, workflow or dependency change. `uv.lock` and `pyproject.toml` must not move.
- No version bump and no release.
- **Do not rewrite the design specs** under `docs/plans/`. They are dated point-in-time records; their
  0.17.3 references document how the drift was found, and rewriting them would destroy that trail.
- No CHANGELOG entry. Precedent is established: pure docs commits (`f05a8bf`, `4579f6a`, `5c0eca1`)
  do not touch `CHANGELOG.md`, because it tracks user-facing changes.

---

## Task 1 — Record the settled dependency queue

**Task ID:** T1
**Depends on:** nothing.

### Outcome

`docs/ROADMAP.md` describes the state of `main` as it is: one open pull request, a settled dependency
batch at the versions that actually merged, and a note about the rebase behaviour that made the
versions differ.

### Current behaviour

See Background. The page contradicts `main` in the three places listed.

### File map

| File | Change |
|---|---|
| `docs/ROADMAP.md` | three edits: the State bullet, the dependency-maintenance section, one phrase in "Next release" |

Nothing else.

### Design

**Edit 1 — `ROADMAP.md:15`.** Replace:

```
- No open code PRs. Seven weekly Dependabot PRs are open (see the dependency queue below).
```

with:

```
- No open code PRs. The only open pull request is Dependabot **#65** (`acevo-sdk` 0.2.1), which is
  waiting on the field validation in item 1 rather than on code.
```

**Edit 2 — replace the whole `### 2. Dependency maintenance (weekly, Dependabot)` section**
(currently `ROADMAP.md:40-55`, from its heading through the paragraph beginning "Handle the safe
updates") with:

```
### 2. Dependency maintenance (weekly, Dependabot)

The 14 November 2026 batch is merged: `ruff` **0.17.4**, `pytest` **9.2.0**, `pytest-asyncio`
**1.4.1.post1**, `mypy` **2.4.1**, `astral-sh/setup-uv` **10.3.3** and
`softprops/action-gh-release` **3.0.4**, plus `ruff-pre-commit` `v0.17.4` in
`.pre-commit-config.yaml`. `pytest` 9.2.0 needed `asyncio_default_fixture_loop_scope` in
`pyproject.toml`; see [the batch spec](plans/dependency-maintenance-batch.md).

Dependabot runs weekly for the `uv`, `github-actions` and `pre-commit` ecosystems; check `gh pr list`
for what is open. Re-check each pull request before merging: rebasing re-resolves to the newest
allowed patch, so the merged version can differ from the one in the diff. Update `uv.lock` with the
project, never by hand.
```

Keep the `### 3. Next release` heading that follows it. Do not renumber the sections.

**Edit 3 — `ROADMAP.md:59`.** In the "Next release" paragraph, replace:

```
Once the timeline refactor is in a release and the dependency/SDK queue has settled, prepare a
```

with:

```
Once the timeline refactor is in a release and the `acevo-sdk` 0.2 item above has settled, prepare a
```

Change nothing else on the page: not the `State (14 November 2026)` date, not the intro paragraph,
not item 1, not "Deferred or external", not "How to pick up an item", not "Non-goals for now".

### Tests

No new test. The proof is the documentation gate that checks every Markdown link in the repository,
plus the format gate.

Required proofs, each reported with its exact command and result:

1. `uv run pytest -q -W error tests/test_docs.py tests/test_docs_links.py` → exit 0. This proves the
   new relative link `plans/dependency-maintenance-batch.md` resolves.
2. `uv run pytest -q -W error` → 522 passed, 4 skipped (unchanged).
3. `uv run pre-commit run --all-files` → exit 0, all hooks Passed (covers trailing whitespace and
   end-of-file).
4. `uv run ruff format --check .` and `uv run ruff check .` → exit 0.
5. `git status --porcelain --untracked-files=all` → exactly `docs/ROADMAP.md`.

### Acceptance criteria

1. `ROADMAP.md` no longer contains the string "Seven weekly Dependabot PRs" or a `pytest 9.1.1 →
   9.2.0 | **fails**` row; the dependency table is gone, replaced by prose.
2. `ROADMAP.md` states that #65 is the only open pull request, and that it waits on field validation.
3. `ROADMAP.md` records the merged versions as `ruff` 0.17.4, `pytest` 9.2.0, `pytest-asyncio`
   1.4.1.post1, `mypy` 2.4.1, `astral-sh/setup-uv` 10.3.3, `softprops/action-gh-release` 3.0.4 and
   `ruff-pre-commit` v0.17.4.
4. `ROADMAP.md` mentions that a rebase re-resolves to the newest allowed patch, and instructs to
   re-check each PR before merging.
5. The "Next release" phrase no longer says "dependency/SDK queue has settled".
6. The link `plans/dependency-maintenance-batch.md` resolves and `tests/test_docs_links.py` passes.
7. `docs/plans/*` is untouched, `CHANGELOG.md` is untouched, `uv.lock` and `pyproject.toml` are
   untouched.
8. No file outside the file map is touched.

### Rollback

Revert the commit. The page returns to describing the pre-batch queue. No runtime surface.

---

## Delivery

- **Repository:** `brake-trainer-evo` only.
- **Branch:** `docs/roadmap-refresh`, one PR.
- **Deploy / candidate:** none. Documentation only; no build or in-game check applies, and the report
  says so.
- **Required checks:** `checks`, `tests (ubuntu-latest, 3.11)`, `tests (ubuntu-latest, 3.12)`,
  `tests (windows-latest, 3.12)`, `windows-build`. `audit` is advisory.
- **Merge order:** single PR, merge after the required checks pass.
- **Post-merge:** none. Nightly refreshes automatically.

## Risks

| Risk | Mitigation |
|---|---|
| The refreshed numbers are wrong again | Every version listed was read from `uv.lock` / `.pre-commit-config.yaml` on `main` at `4b087ce`; acceptance criterion 3 names them explicitly so a reviewer can compare. |
| Removing the table loses the history of what was pending | The merge results live in the git history and in `docs/plans/dependency-maintenance-batch.md`; the page's own rule says transient PR state is removed when handled. |
| The next Dependabot cycle makes the new prose stale | The section now points at `gh pr list` instead of listing PRs, so it does not need editing each week. |
