# Game-log fixtures

Small excerpts from real Assetto Corsa EVO game logs (build 0.9.1, Monza), kept verbatim
apart from the Steam and car IDs in `connect.txt`, which are placeholders of the same shape.
They pin the exact line shapes the parser sees; full logs are not committed because they are
large and contain session data.

`notification_block.txt` is the field-log moment where a cut was reported 2.15 s after the S1
line at Monza. The matching app log put the car at 36.3% of the lap there, which is where the game
judged the cut (Roggia); the drop belongs to S2, not to S1 a fixed distance behind it.
`noise.txt` holds the lines around that block that must not produce a second event.

To add a case, put the excerpt in a new `.txt` file here and add a short test in
`tests/test_gamelog.py` using `_parse_fixture`; assert the `(cut, split)` events it must produce.
Keep the file to the lines needed for that one behaviour.
