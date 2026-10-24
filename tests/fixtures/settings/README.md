# Settings fixtures

Real settings files from older app versions.

`settings_0.3.11.json` is the file shared from 0.3.11. It predates `settings_version` and still has
the retired `cut_give_back_m: 0.0`. The test loads it, checks that the key is ignored and the file is
written back with the current version and without it.
