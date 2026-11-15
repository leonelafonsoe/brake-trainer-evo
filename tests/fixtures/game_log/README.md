# Game-log fixtures

Small excerpts from real evidence, kept verbatim. They pin the exact line shapes the parser sees;
full logs are not committed because they are large and contain session data. The field excerpts
are from Assetto Corsa EVO build 0.9.1 at Monza.

`notification_block.txt` is the field-log moment where a cut was reported 2.15 s after the S1
line at Monza. The matching app log put the car at 36.3% of the lap there, which is where the game
judged the cut (Roggia); the drop belongs to S2, not to S1 a fixed distance behind it.
`noise.txt` holds the lines around that block that must not produce a second event.

`penalty_sdk_build.txt` is an SDK-shaped excerpt, not a replacement for `notification_block.txt`:
the SDK's 0.2.2 parser does not recognise our build's `Adding notification ...` line. Its two lines
are copied verbatim:

- the addition line, from the SDK's 0.2.2 regression data:
  `[2026-08-18 23:13:02.935] [gameface] [warning] true {PENALTY_ADDED_KEY} #0`;
- the clearance line, from `notification_block.txt` (build 0.9.1):
  `[2026-10-23 01:40:35.562] [gameface] [warning] false {PENALTY_CLEARED_KEY} #296`.

It pins that the parser accepts the SDK's addition shape and ignores a real clearance line.

To add a case, put the excerpt in a new `.txt` file here and add a short test in
`tests/test_gamelog_parser.py` using `_parse_fixture`; assert the `(cut, split)` events it must
produce. Keep the file to the lines needed for that one behaviour.
