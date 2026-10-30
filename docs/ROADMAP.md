# Roadmap and pending work

Status after **0.7.0**: the post-0.6.0 batch is released. It shipped the race-cut guard, the global
pause hotkey, the Windows adapter tests, the settings key rename (`SETTINGS_VERSION` 5), the HUD
colour constants and the typing/engine-protocol cleanup. The [changelog](../CHANGELOG.md) has the
detail.

This page now tracks only the work that is deliberately deferred or needs input from outside the
repository.

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

## Remaining

| Item | Value | Risk | Effort |
|---|---|---|---|
| `acevo-sdk` 0.2 upgrade | Future game support | High (field) | M-L |
| Code signing | Trust / SmartScreen | External | — |

## 1. `acevo-sdk` 0.2 upgrade (field-tested)

**Current state:** pinned to `acevo-sdk>=0.1.1,<0.2.0`. The 0.2.0 release changes log parsing,
lap-authority and validity handling; the app's pin comment says 0.2.0 withholds frames until a clean
lap boundary and starves the live overlay. Dependabot is configured to ignore 0.2.x.

**To revisit:** remove the ignore, bump the pin, check `LapState.PUSH` → `LapState.VALID` usage,
verify live frames, sector lines, cuts and game-exit detection on track, then update the comment,
docs and ignore. This is a field-validation task, not a blind dependency bump.
**Branch:** `deps/acevo-sdk-0.2`.

## 2. Code signing (external)

The installer and exe are unsigned, so SmartScreen warns. Code signing needs a certificate or a
service such as SignPath (check eligibility against the non-commercial licence). If adopted, add the
signing step to `release.yml`, sign both the exe and the installer before checksums, and document
the certificate/secret rotation. No code change until the account and certificate exist.

---

## Non-goals for now

- A docs site/mkdocs, tox/nox, a devcontainer or pytest-xdist: the current uv + GitHub Actions setup
  is proportionate.
- QSettings for app settings: the versioned JSON is what makes the archive/reset policy explicit.
- A large engine rewrite: the learning behaviour is subtle and well tested; change it only with a
  regression test.
