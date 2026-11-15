# Roadmap and pending work

This is the single list of pending work. It records the release state, the immediate queue and the
ideas that are deliberately deferred or need input from outside the repository. Transient PR state
is noted with the date it was checked and is removed when handled.

## State (14 November 2026)

- **0.7.0** shipped the race-cut guard, the global pause hotkey, the Windows adapter tests, the
  settings key rename (`SETTINGS_VERSION` 5), the HUD colour constants and the
  typing/engine-protocol cleanup (29 October 2026).
- **0.7.1** is the current versioned release (14 November 2026): the **timeline interpolation
  refactor** (PR #60) plus the tooling alignment (`ruff` pre-commit pin, pytest-asyncio loop scope).
  The [changelog](../CHANGELOG.md) has both entries.
- The **`acevo-sdk` 0.2 move** is implemented on `deps/acevo-sdk-0.2` (14 November 2026): 0.2.2 is
  pinned, the frame gate and the graphics-region read are shimmed, both penalty addition shapes
  count, replay/pause frames are ignored and alternate layouts key separately. It merges after the
  `windows-build` candidate session; Dependabot **#65** is superseded by this branch and closed as
  part of its delivery.
- No other pull request is open.
- Settings schema is **5** (old v4 files were archived on upgrade); learned data is **1**. No
  migration is pending.

## Immediate queue

### 1. Dependency maintenance (weekly, Dependabot)

The 14 November 2026 batch is merged: `ruff` **0.17.4**, `pytest` **9.2.0**, `pytest-asyncio`
**1.4.1.post1**, `mypy` **2.4.1**, `astral-sh/setup-uv` **10.3.3** and
`softprops/action-gh-release` **3.0.4**, plus `ruff-pre-commit` `v0.17.4` in
`.pre-commit-config.yaml`. `pytest` 9.2.0 needed `asyncio_default_fixture_loop_scope` in
`pyproject.toml`; see [the batch spec](plans/dependency-maintenance-batch.md).

Dependabot runs weekly for the `uv`, `github-actions` and `pre-commit` ecosystems; check
`gh pr list` for what is open. Re-check each pull request before merging: rebasing re-resolves to
the newest allowed patch, so the merged version can differ from the one in the diff. Update
`uv.lock` with the project, never by hand.

### 2. Next release (separate task)

0.7.1 is a **patch** because nothing in it is user-facing. The `acevo-sdk` 0.2 move is the opposite:
it touches log parsing, lap authority and validity handling, so release it separately as **0.8.0**
if anything becomes visible. Cutting that release is a separate task after this pull request is
merged and field-tested; this branch does not bump the version. Then follow the
[release pipeline](DEVELOPMENT.md#release-pipeline): bump, changelog, gates,
`release_notes.py --check`, then tag.

## Deferred or external

### Code signing

The installer and exe are unsigned, so SmartScreen warns; the README says signing is a planned
improvement. It needs a certificate or a service such as SignPath (check eligibility against the
non-commercial licence). If adopted, add the signing step to `release.yml`, sign both the exe and
the installer before checksums, and document the certificate/secret rotation. No code change until
the account and certificate exist.

---

## How to pick up an item

1. Branch from `main` and keep one item per PR.
2. Follow the gates in [DEVELOPMENT.md](DEVELOPMENT.md): pre-commit, ruff, both `mypy` passes
   (`--platform win32` too), generated settings, tests with `-W error`, coverage floor.
3. Add a test for the behaviour you change. Offscreen UI tests use
   `pytest.mark.usefixtures("close_qt_windows")`.
4. Add a `CHANGELOG.md` line under `## Unreleased` and update the owning doc page.
5. Wait for CI. Download the PR's `windows-build` artifact and test in-game when the change is
   user-visible. Merge only after that.
6. Pre-1.0 policy: a settings or learned-data layout change may archive old files and start from
   defaults. **Never delete user data**; archive by move.

## Non-goals for now

- A docs site/mkdocs, tox/nox, a devcontainer or pytest-xdist: the current uv + GitHub Actions setup
  is proportionate.
- QSettings for app settings: the versioned JSON is what makes the archive/reset policy explicit.
- A large engine rewrite: the learning behaviour is subtle and well tested; change it only with a
  regression test.
