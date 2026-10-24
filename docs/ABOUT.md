# About this project

## How it was made

Brake Trainer EVO is a **"vibe coded"** project: almost all of the code, tests and documentation were
written by an AI assistant, [Claude](https://www.anthropic.com/claude) (Anthropic), over a long
conversation with the maintainer. The maintainer decides what to build, runs it in Assetto Corsa
EVO, and reports what they see; the assistant writes, tests and revises the code. Features such as
the sector-based learning, the reference car, warm-up laps and the HUD style came from that back and
forth.

That has consequences you should know about before relying on it.

## What was verified, and how

| Area | How it was checked |
| --- | --- |
| Learning engine, sectors, warm-up, validity rules, reference car, pause | Automated scenario tests with a synthetic driver on a fake track (`tests/`) |
| Settings, data files, status line, telemetry reader logic, audio generation | Automated unit tests, with fakes for the game and the SDK |
| Code quality | `ruff` (lint + format) and `mypy --strict`, run before each release |
| The windows' appearance | Rendered offscreen and inspected as screenshots |
| **Real game behaviour** (telemetry values, overlay over the game, beeps, game-exit detection, the Windows build) | **Only by the maintainer's play-testing.** The AI could not run the game or Windows |

Things that were reasoned about but never confirmed against the real game are called out in the
docs ("I have not verified ...", for example how the race-cut fields behave on kerbs).

## What this means for you

- Treat it as hobby software. It may have bugs the tests do not cover, especially anything that
  depends on live game data.
- Read the code before trusting it, as you would any code from a stranger. It is small and
  commented.
- The AI can be confidently wrong. If a doc or comment makes a claim about the game, check it.
- It only reads telemetry and never touches the game files, which keeps the risk low, but see the
  disclaimer in the [README](../README.md#disclaimer).

## Contributing with AI

AI-assisted pull requests are welcome, with a human check. The rules are in
[CONTRIBUTING.md](../CONTRIBUTING.md#ai-assisted-contributions).

## Credits

See the [README](../README.md#credits): the original Brake Trainer by AugGust, and acevo-sdk by Gleb
Zverinskiy, without which this would not be possible.
