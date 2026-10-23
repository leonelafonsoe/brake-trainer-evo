# Game-log fixtures

Small excerpts from real Assetto Corsa EVO game logs (build 0.9.1, Monza), kept verbatim
apart from the Steam and car IDs in `connect.txt`, which are placeholders of the same shape.
They pin the exact line shapes the parser sees; full logs are not committed because they are
large and contain session data.

`notification_block.txt` is the field-log moment where a cut was reported 2.15 s after the S1
line at Monza. The matching app log put the car at 36.3% of the lap there, so reading the report
back by the game's 500 m window puts the cut at about 23.2%, in S1, not in S2 where it landed.
`noise.txt` holds the lines around that block that must not produce a second event.
