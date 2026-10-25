# Settings fixtures

Real settings files from older app versions.

`settings_0.3.11.json` is the file shared from 0.3.11. It predates versioned settings and still has
the retired `cut_give_back_m: 0.0`. The test loads it, checks that the app starts from defaults and
that the whole file is moved aside intact.
