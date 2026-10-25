# Security policy

## Supported versions

Security fixes are made for the latest release and `main`. Older releases may be asked to upgrade
rather than patched separately.

## Reporting a vulnerability

**Please do not open a public issue for a security problem.** Use GitHub's private vulnerability
reporting:

<https://github.com/leonelafonsoe/brake-trainer-evo/security/advisories/new>

If that form is unavailable, open a minimal public issue asking for a private channel and do not
include the details.

Please include:

- the app version and `build=` from the first `startup ...` line of the log;
- the operating system and how the app was installed (installer, portable zip, source);
- what an attacker can do and what they need (a local file, a crafted game log, a dependency or
  physical access);
- the smallest reproduction you can share, with personal data removed.

Reports are handled on a best-effort basis by the maintainer. Please give a reasonable amount of
time to investigate and release a fix before disclosing publicly.

## Scope

This is a local Windows companion app. It reads telemetry through `acevo-sdk`, follows the game's
log, writes its own files under `%APPDATA%\BrakeTrainerEvo`, and opens no network ports. Relevant
security issues include, but are not limited to:

- unsafe handling of settings or learned-data files (path traversal, overwriting a file this build
  could not read, following links unexpectedly);
- parsing a crafted game log or telemetry frame in a way that executes code or exhausts memory;
- a vulnerable dependency shipped in the installer or portable zip;
- an installer that writes outside its install folder or elevates when it should not.

Game bugs, anti-cheat questions, performance reports and feature requests are not security issues;
use the normal issue templates for those.
