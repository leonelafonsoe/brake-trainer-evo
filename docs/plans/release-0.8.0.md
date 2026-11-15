# Technical Design Specification — release 0.8.0

**Spec branch:** `release/0.8.0`
**Base commit:** `27f4c8e0daa48e3e8102a683950de63ce0917407` (`main`, "Merge pull request #74 …")
**Repository:** `brake-trainer-evo`
**Status:** awaiting GO.

## Objective

Cut **0.8.0** from the merged `acevo-sdk` 0.2.2 move. This is a minor release, not a patch: the
move changes user-visible behaviour (outlap frames, replay/pause filtering, layout-specific learned
data, penalty handling). The roadmap's own rule — "release it separately as 0.8.0 if anything
becomes visible" — applies.

No application code changes. The release is the version bump, the changelog section, the roadmap
state, the full gates, the release-notes check, the PR, the `v0.8.0` tag, and verification of the
Release workflow's installer, zip and checksums.

## Current state

- `main` is at `27f4c8e`, the merge of PR #74 (`deps/acevo-sdk-0.2`); PR #65 is closed.
- `pyproject.toml` and `src/brake_trainer/__init__.py` say **0.7.1**; `AGENTS.md` targets **0.7.1**.
- `CHANGELOG.md` has a non-empty `## Unreleased` with the seven `acevo-sdk` move bullets.
- `docs/ROADMAP.md` still says the move is "implemented on `deps/acevo-sdk-0.2`" and "merges after
  the candidate"; that is stale after #74.
- The release pipeline is `bump_version.py` → review/commit/PR → merge → `git tag vX.Y.Z` →
  `release.yml` builds the installer, portable zip and checksums. The workflow refuses a tag that
  does not match the project version, a missing/empty version section, or a non-empty
  `## Unreleased`.
- `release_notes.py --tag v0.8.0 --check` is the local pre-tag check.

## Non-goals

- No code, dependency, schema or UI change.
- No new features or fixes; the release notes describe what PR #74 already shipped.
- No code signing (separate external item).
- No post-release roadmap follow-up PR: the roadmap is updated in this release PR.

---

## Task R1 — Prepare the 0.8.0 release commit

**Task ID:** R1
**Depends on:** nothing (the merged #74).

### Outcome

The project is version **0.8.0** everywhere, `## Unreleased` is empty, `## 0.8.0 - <date>` carries
the move's notes, the roadmap records 0.8.0 as current, the lock's root version matches, and the
local release check passes. The release PR is ready to merge; the tag is a delivery step, not part
of this task.

### File map

| File | Change |
|---|---|
| `pyproject.toml` | version `0.8.0` (via `bump_version.py`) |
| `src/brake_trainer/__init__.py` | `__version__ = "0.8.0"` (via the script) |
| `AGENTS.md` | target version `0.8.0` (via the script) |
| `uv.lock` | root project version `0.8.0` (via the script's `uv lock`) |
| `CHANGELOG.md` | `## Unreleased` emptied; `## 0.8.0 - 2026-11-15` with the existing bullets |
| `docs/ROADMAP.md` | record 0.8.0 as current; remove the stale branch/candidate text; update the queue |

Nothing else. No source, tests, docs other than the roadmap, or workflow changes.

### Design

1. **Bump with the project tool**, from the repo root on a clean `release/0.8.0` branch:
   `uv run python scripts/bump_version.py 0.8.0`
   The script sets `pyproject.toml`, `__init__.py`, `AGENTS.md`, moves `## Unreleased` to
   `## 0.8.0 - <today>` (2026-11-15), leaves `## Unreleased` empty, and runs `uv lock` for the root
   version. Do not hand-edit the version fields or the lock.
2. **Review the changelog.** The seven existing bullets become the 0.8.0 notes. Keep them under
   `### Changed`; do not invent a new feature or a measurement. The release-notes body is generated
   from this section.
3. **Roadmap.** Update the 14 November state to 15 November:
   - **0.8.0 is the current versioned release** (15 November 2026): the `acevo-sdk` 0.2.2 move —
     outlap frames, race-cut region read, both penalty addition shapes, replay/pause filtering,
     layout-specific keys. Link the changelog.
   - Remove the "implemented on `deps/acevo-sdk-0.2` / merges after the candidate" bullet and the
     stale #65 sentence; #65 is closed.
   - Remove the "Next release (separate task)" item or replace it with the next release after
     0.8.0; keep dependency maintenance as item 1. Do not invent a future version.
   - Keep the settings/data version note.
4. **Commit** the six files on `release/0.8.0` (the spec is committed by itself first).
5. **Verify**:
   - `pyproject.toml`, `__init__.py` and `AGENTS.md` all say 0.8.0.
   - `uv.lock` root version is 0.8.0; no other package changed.
   - `## Unreleased` is empty; `## 0.8.0 - 2026-11-15` is non-empty.
   - `uv run python scripts/release_notes.py --tag v0.8.0 --check` → pass.
   - Full gate: `uv sync --locked --extra dev`, `pre-commit --all-files`, both ruff commands, both
     mypy passes, `pytest -W error`, `pytest -W error --cov`, `gen_settings_doc.py --check`.

### Tests

No new test. The existing `tests/test_docs.py::test_the_agents_target_version_matches_the_package`
and the generated-settings checks cover the version alignment; the release check and the full gate
are the proof.

### Acceptance criteria

1. `pyproject.toml`, `src/brake_trainer/__init__.py` and `AGENTS.md` say **0.8.0** and match.
2. `uv.lock`'s root version is 0.8.0; its diff moves no dependency version.
3. `CHANGELOG.md` has an empty `## Unreleased` and a non-empty `## 0.8.0 - 2026-11-15` with the
   seven move bullets; no version section is duplicated.
4. `docs/ROADMAP.md` records 0.8.0 as current, removes the stale branch/candidate text and #65
   sentence, and keeps the queue coherent.
5. `release_notes.py --tag v0.8.0 --check` passes locally.
6. The full gate passes.
7. Only the six mapped files change (plus the spec commit).

### Rollback

Before the tag: revert the release PR; version returns to 0.7.1, `## Unreleased` is restored. After
the tag: delete the GitHub release and the `v0.8.0` tag, fix forward, and re-tag; the 0.7.1 release
stays untouched.

---

## Delivery

- **Repository:** `brake-trainer-evo` only.
- **Branch:** `release/0.8.0`, from `27f4c8e`; one PR.
- **Deploy:** none. The GitHub Release is published by `release.yml`, not a deploy.
- **PR:** `release/0.8.0` → `main`, title `release: 0.8.0`.
- **Required checks:** `checks`, `tests (ubuntu-latest, 3.11)`, `tests (ubuntu-latest, 3.12)`,
  `tests (windows-latest, 3.12)`, `windows-build`; `audit` advisory.
- **Merge:** merge commit on `main`; do not squash (the tag must point at the released tree).
- **Tag:** after the merge, `git tag v0.8.0 <merge-commit> && git push origin v0.8.0`. Do not tag the
  branch before the merge. The tag must be on `main`'s merge commit.
- **Release workflow:** wait for `release.yml` to pass. It runs the release-notes check, the same
  gates plus coverage/audit, builds the exe, smoke-tests it, builds the installer, writes
  `SHA256SUMS.txt`, and publishes. Verify:
  - `BrakeTrainerEvo-0.8.0-setup.exe`,
  - `BrakeTrainerEvo-0.8.0-windows.zip`,
  - `SHA256SUMS.txt`,
  - the release body is the 0.8.0 changelog section,
  - the checksums match the assets.
- **Candidate:** the 0.2.2 code was field-tested on the PR #74 `windows-build` artifact. The release
  workflow's smoke test starts the packaged exe; the maintainer may install the 0.8.0 installer and
  confirm its startup line reads `startup app=0.8.0 build=<tag commit>`. If that install test is
  skipped, the report says so.
- **Post-release:** none. Nightly refreshes from `main`; the changelog/roadmap are in the PR. The
  next release is a separate task.
- **Merge order:** single repository, single PR.

## Risks

| Risk | Mitigation |
|---|---|
| `uv lock` moves an unrelated package during the bump | The bump script runs it; inspect the lock diff and require only the root version. |
| The release workflow refuses the tag (version, empty notes, non-empty Unreleased) | The local `release_notes.py --tag v0.8.0 --check` and the full gate run before the tag. |
| The tag is pushed before the merge or on the branch | Tag the merge commit on `main`; verify `git rev-parse v0.8.0` equals the merge commit. |
| The Windows build/installer fails | `release.yml` is fail-closed; fix forward and re-tag (delete the bad release/tag first). |
| The installer is unsigned | Known and documented; SmartScreen warns; code signing is deferred. |
| The release notes overstate the field evidence | Keep the existing changelog bullets; do not add unproven claims. The residual race/Indy evidence stays in the PR #74 report. |
