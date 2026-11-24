# Technical Design Specification — release 0.8.1

**Spec branch:** `release/0.8.1`
**Base commit:** `944d551` (`main`, "Merge pull request #84 from leonelafonsoe/deps/batch-2026-11-22")
**Repositories:** `brake-trainer-evo` only
**Status:** awaiting GO.

## 1. Objective

Cut **0.8.1** from the merged November dependency batch. This is a patch release, not a minor: the
only user-visible change is a fix — frames captured while the camera follows another car no longer
teach braking points — plus a dev-facing dependency refresh. No new capability, no schema change,
no settings change.

Deliverables:

1. the version set everywhere with the changelog section assembled (Task R1);
2. a PR through the normal gates;
3. after merge, the `v0.8.1` tag, which is what `release.yml` turns into the installer, the portable
   zip and `SHA256SUMS.txt`;
4. a post-tag check that the published assets exist, are non-empty, and match their checksums.

## 2. Non-goals

- **No 0.9.0.** There is nothing feature-level in `## Unreleased`, and 0.8.0's minor bump was for a
  multi-part SDK move, not a single fix.
- **No code change.** The release commit touches version numbers, the changelog, the roadmap and the
  lock's root version only. Any source change would be a different spec.
- **No re-lock.** `uv lock` must only move the root project version; if it re-resolves a package,
  stop and report.
- **No pre-release tag.** `v0.8.1` is a final release; the installer build is fail-closed anyway.
- **No candidate step.** The behaviour in this release is exactly what #84's `windows-build`
  artifact carried, and the maintainer already exercised it. Nothing user-facing changes between
  that artifact and the tag.

## 3. Investigation

### 3.1 What is being released

`## Unreleased` on `main` holds one bullet: the spectated-car fix from PR #84. Six dependency PRs
merged around it: `pre-commit-hooks` v6.0.0 (#75), `acevo-sdk` 0.2.3 (#83), `pytest-asyncio` 1.5.0
(#77), `ruff` 0.17.6 (#81) with its `pre-commit` hook (#82), and `astral-sh/setup-uv` 10.4.0 (#80).
Only the first is user-facing.

### 3.2 How the release is assembled

`scripts/bump_version.py <version>` does all of it in one run:

- moves the non-empty `## Unreleased` body into `## <version> - <today>` and leaves `## Unreleased`
  empty (it refuses an empty Unreleased, an existing section, or a bad version);
- rewrites `version` in `pyproject.toml`, `__version__` in `src/brake_trainer/__init__.py`, and the
  `This branch targets **x.y.z**` sentence in `AGENTS.md`;
- runs `uv lock` so the lock's root version matches what `--locked` installs.

`scripts/release_notes.py --tag v0.8.1 --check` then proves the tag, both version files and a
non-empty changelog section agree, and that `## Unreleased` has no notes left. CI's `checks` job and
`tests/test_release_tools.py::test_the_project_version_and_the_tag_contract_agree` enforce the same
contract.

Today is 24 November 2026, so the section date is `2026-11-24`, matching the roadmap's State
heading.

## 4. Constraints

1. `bump_version.py` is the only supported way to set the version; do not hand-edit the numbers.
2. The changelog bullet must be true at merge: the dependency refresh is described as dev-facing,
   and the fix is described exactly as the code behaves.
3. `## Unreleased` must be empty when the tag is pushed, or `release.yml` refuses to publish.
4. The tag is pushed **after** the merge, from the merge commit, never from the branch.

---

## Task R1 — Prepare the 0.8.1 release commit

**Task ID:** R1
**Depends on:** the November batch merged (`944d551`).

### Outcome

The project is version **0.8.1** everywhere, `## Unreleased` is empty, `## 0.8.1 - 2026-11-24`
carries the release notes, the roadmap records 0.8.1 as current, and the lock's root version
matches.

### Current behaviour

`pyproject.toml:7` and `src/brake_trainer/__init__.py:3` say `0.8.0`; `AGENTS.md` targets `0.8.0`;
`uv.lock` records the root project at `0.8.0`; `CHANGELOG.md` has a non-empty `## Unreleased` with
the spectate fix and no `0.8.1` section; `docs/ROADMAP.md` State calls 0.8.0 the current release.

### File map

| File | Change |
|---|---|
| `CHANGELOG.md` | dependency bullet under `## Unreleased`; then the script moves the section to `## 0.8.1 - 2026-11-24` |
| `pyproject.toml` | `version = "0.8.1"` (via `bump_version.py`) |
| `src/brake_trainer/__init__.py` | `__version__ = "0.8.1"` (via the script) |
| `AGENTS.md` | `This branch targets **0.8.1**` (via the script) |
| `uv.lock` | root project version `0.8.1` (via the script's `uv lock`) |
| `docs/ROADMAP.md` | State: 0.8.1 current, 0.8.0 previous; "Immediate queue" item 2 names 0.8.1 |
| `docs/plans/release-0.8.1.md` | this spec |

Nothing else.

### Design

1. **`CHANGELOG.md`, before the bump.** Rework `## Unreleased` so the release section reads
   `### Changed` then `### Fixed`, matching the older sections' order (for example 0.4.0). The
   existing `### Fixed` bullet stays word for word; add above it:

   ```markdown
   ## Unreleased

   ### Changed

   - Dependencies refreshed: `acevo-sdk` 0.2.3, `ruff` 0.17.6 with its `pre-commit` hook,
     `pytest-asyncio` 1.5.0, `pre-commit-hooks` 6.0.0 and `astral-sh/setup-uv` 10.4.0. These are
     tooling and library updates; the app's own behaviour changes only where the fix below says so.
   ```

   "The fix below" is accurate because `### Fixed` follows `### Changed`.

2. **Run the bump** from the repository root:

   ```bash
   uv run python scripts/bump_version.py 0.8.1
   ```

   Expect the script's message `version set to 0.8.1; review the diff, commit, then tag v0.8.1`.
   It rewrites the four files and runs `uv lock`. Inspect `git diff uv.lock`: it must show only the
   root package's version line. If any other package moved, stop and report — that is a re-lock, not
   a release.

3. **`docs/ROADMAP.md`, "State".** Keep the bullets in version order: 0.7.0, 0.7.1, 0.8.0, 0.8.1.
   Reword the two older bullets so exactly one claims "previous", and insert the new one after the
   0.8.0 bullet:

   ```markdown
   - **0.7.1** was the release before that (14 November 2026): the **timeline interpolation
     refactor** (PR #60) plus the tooling alignment (`ruff` pre-commit pin, pytest-asyncio loop scope).
   - **0.8.0** was the previous release (15 November 2026): the **`acevo-sdk` 0.2.2 move** —
     ...
   - **0.8.1** is the current versioned release (24 November 2026): the **spectated-car learning
     fix** and the November dependency batch (`acevo-sdk` 0.2.3, `ruff` 0.17.6,
     `pytest-asyncio` 1.5.0, `pre-commit-hooks` 6.0.0, `astral-sh/setup-uv` 10.4.0). The
     [changelog](../CHANGELOG.md) has the entry.
   ```

   Change only those phrases in the 0.7.1 and 0.8.0 bullets; the rest of their text stays word for
   word. Leave the State heading at 24 November 2026 and leave "No other pull request is open."
   alone; it is true once this PR merges.

4. **`docs/ROADMAP.md`, "Immediate queue" item 2.** The previous release commit rewrote this item,
   so it must move again now that 0.8.1 is the release being cut: change the heading
   `### 2. Next release after 0.8.0` to `### 2. Next release after 0.8.1` and the body's opening
   `0.8.0 is cut;` to `0.8.1 is cut;`. Leave the rest of that item — the pointer to the release
   pipeline, bump, changelog, gates, `release_notes.py --check`, tag — word for word.

5. **Do not** touch any other doc that mentions 0.8.0 — the other hits are historical specs and
   their dates.

### Tests

No new test: the version contract is already pinned by
`tests/test_release_tools.py::test_the_project_version_and_the_tag_contract_agree`, which requires
both version files to agree, the version to be a valid tag, and a non-empty changelog section for it.

**Required proofs** (report exact commands and output):

```bash
uv run python scripts/bump_version.py 0.8.1
uv run python scripts/release_notes.py --tag v0.8.1 --check
uv run pytest -q -W error tests/test_release_tools.py
uv run python scripts/gen_settings_doc.py --check
git diff --stat
git diff uv.lock
git diff CHANGELOG.md
```

Then the fast gate:

```bash
uv run ruff format --check . && uv run ruff check . && uv run mypy
uv run pytest -q -W error
```

### Acceptance criteria

1. `pyproject.toml`, `src/brake_trainer/__init__.py` and `AGENTS.md` all read `0.8.1`; `uv.lock`'s
   root version is `0.8.1` and **no other line of `uv.lock` changed**.
2. `CHANGELOG.md` has an empty `## Unreleased` and a `## 0.8.1 - 2026-11-24` section containing the
   `### Changed` dependency bullet and the existing `### Fixed` spectate bullet, word for word.
3. `uv run python scripts/release_notes.py --tag v0.8.1 --check` exits 0.
4. `docs/ROADMAP.md` State records 0.8.1 as current and 0.8.0 as previous, the bullets stay in
   version order, exactly one bullet says "previous", and "Immediate queue" item 2 names 0.8.1 as
   the release just cut.
5. `uv run pytest -q -W error tests/test_release_tools.py` and the fast gate exit 0, including the
   whole suite.
6. No file outside the file map changed; no source file changed.

### Rollback

Revert the commit before tagging. After the tag is pushed, a bad release is removed from the
Releases page and its tag deleted (`git push --delete origin v0.8.1`) before a fixed tag is pushed;
the release workflow is fail-closed, so a failed build publishes nothing to clean up.

---

## 5. Delivery

### 5.1 Repositories and branches

| Repository | Spec branch | PR |
|---|---|---|
| `brake-trainer-evo` | `release/0.8.1`, from `main` at `944d551` | one PR carrying R1 |

### 5.2 Deploy, candidate and environment

**No deploy and no deployed environment.** The profile defines none, so there is no artifact-identity
chain and no "unverifiable" gap.

**Candidate step: not applicable.** The user-facing change shipped in #84 and was exercised in-game
on that PR's `windows-build` artifact. Between that artifact and the tag the only differences are
version strings, the changelog, the roadmap and the lock's root version — nothing that can be driven
in-game. Record it as not applicable rather than skipped-after-attempt.

### 5.3 Required checks

The five required jobs on the PR: `checks`, `tests (ubuntu-latest, 3.11)`,
`tests (ubuntu-latest, 3.12)`, `tests (windows-latest, 3.12)`, `windows-build`. `audit` is advisory
and may not appear — this PR changes no `uv.lock` package and no `pyproject.toml` dependency.

### 5.4 Tag and publication

After the PR is merged:

1. confirm `main`'s `pyproject.toml` reads `0.8.1` and `## Unreleased` is empty;
2. ask the maintainer for explicit confirmation, then `git tag v0.8.1 <merge-commit>` and
   `git push origin v0.8.1` — **from the merge commit, never the branch**;
3. watch the Release workflow. It fails closed on a missing installer, zip or checksum file, a bad
   checksum, a tag/version mismatch, or a non-empty `## Unreleased`;
4. verify the published release: exactly three assets (`BrakeTrainerEvo-0.8.1-setup.exe`,
   `BrakeTrainerEvo-0.8.1-windows.zip`, `SHA256SUMS.txt`), all non-empty; download `SHA256SUMS.txt`
   and the two binaries and check the hashes match; confirm the body is the 0.8.1 changelog section
   and that the release is not marked as a pre-release.

### 5.5 Post-release

None required. Nightly refreshes from `main` on its own and keeps its rolling tag. No submodule or
pointer exists. The roadmap already records 0.8.1 as current in R1; no further docs change is needed.

## 6. Risks and what will not be tested

| Risk | Mitigation |
|---|---|
| `uv lock` re-resolves a package during the bump | The diff check is an acceptance criterion; stop and report if anything but the root version moved. |
| The tag is pushed against the branch instead of the merge commit | §5.4 pins the merge commit; the release body is generated from the changelog, so a wrong commit would still publish the wrong tree. |
| The changelog bullet overstates the dependency refresh | It says tooling/library updates and defers behaviour to the fix; `acevo-sdk` 0.2.3's only semantic change is in a class this app does not use. |
| The installer or zip is missing or a checksum is wrong | The workflow fails closed; nothing is published and the tag is deleted. |
| Windows-only packaging failure | Cannot be reproduced here; `windows-build` on the PR and the Release workflow are the authority. |

**Not tested by this spec, and to be reported as such:** the packaged installer and zip beyond the
workflow's own assertions and the checksum check; the in-game behaviour (already covered by #84's
candidate step); the Windows test leg locally (CI's authority).
