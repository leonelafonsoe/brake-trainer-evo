# Roadmap and pending work

This is the single list of pending work. It records the release state, the immediate queue and the
ideas that are deliberately deferred or need input from outside the repository. Transient PR state
is noted with the date it was checked and is removed when handled.

## State (14 November 2026)

- **0.7.0** is the current versioned release (29 October 2026). It shipped the race-cut guard, the
  global pause hotkey, the Windows adapter tests, the settings key rename (`SETTINGS_VERSION` 5),
  the HUD colour constants and the typing/engine-protocol cleanup. See the
  [changelog](../CHANGELOG.md).
- `main` also contains the **timeline interpolation refactor** (PR #60), recorded under
  `## Unreleased`. Nightly is green for that commit, but no versioned release contains it yet.
- No open code PRs. Seven weekly Dependabot PRs are open (see the dependency queue below).
- Settings schema is **5** (old v4 files were archived on upgrade); learned data is **1**. No
  migration is pending.

## Immediate queue

### 1. `acevo-sdk` 0.2 (field-tested)

**Current state:** the app is pinned to `acevo-sdk>=0.1.1,<0.2.0`. Dependabot PR **#65** proposes
0.1.1 → 0.2.1 and passes CI. The existing `ignore: 0.2.x` rule did **not** match 0.2.1; fix the
range (for example `>=0.2.0, <0.3.0`) as part of this change.

0.2 changes log parsing, lap-authority and validity handling. The old pin comment says 0.2.0
withholds frames until a clean lap boundary, which starves the live overlay. CI cannot prove any of
that.

**To do:**

- Use #65 (or a fresh `deps/acevo-sdk-0.2` branch) and review the 0.2 API changes, especially
  `LapState.PUSH` → `LapState.VALID` usage.
- Fix the pin comment, the Dependabot ignore range and the dependency/docs notes.
- Build the Windows artifact and test on track: **live frames are not withheld**, sector lines,
  cuts and game-exit detection, and the game's validity handling.
- Merge only after that session. This is a field-validation task, not a blind bump.

### 2. Dependency maintenance (weekly, Dependabot)

Checked 14 November 2026; re-check before merging because Dependabot rebases.

| PR | Update | CI |
|---|---|---|
| #61 | `astral-sh/setup-uv` 10.3.2 → 10.3.3 | pass |
| #62 | `ruff` 0.17.2 → 0.17.3 | pass |
| #63 | `pytest` 9.1.1 → 9.2.0 | **fails** |
| #64 | `mypy` 2.4.0 → 2.4.1 | pass |
| #65 | `acevo-sdk` 0.1.1 → 0.2.1 | pass (field test still required) |
| #66 | `pytest-asyncio` 1.4.0 → 1.4.1 | pass |
| #67 | `softprops/action-gh-release` 3.0.3 → 3.0.4 | pass |

Handle the safe updates; keep #63 open until the failing leg is understood and fixed; treat #65 as
the SDK task above. Update `uv.lock` with the project, never by hand.

### 3. Next release

Once the timeline refactor is in a release and the dependency/SDK queue has settled, prepare a
release. It is a **patch** by default (**0.7.1**) unless a user-facing feature lands before the tag.
Follow [the release pipeline](DEVELOPMENT.md#release-pipeline): bump, changelog, gates,
`release_notes.py --check`, then tag. There is no tag or release branch yet.

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
