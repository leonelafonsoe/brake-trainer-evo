# Settings fixtures

Real settings files from older app versions.

`settings_0.3.11.json` is the file shared from 0.3.11. It predates `settings_version` and still has
`cut_give_back_m: 0.0`, the old default. The test loads it, checks the one-time migration to the
game's 500 m window, saves it, and verifies that a later deliberate `0` is preserved.
