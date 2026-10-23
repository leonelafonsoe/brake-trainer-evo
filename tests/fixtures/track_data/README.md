# Track-data fixtures

Real `version: 1` files shared from a 0.3.11 install (Ferrari 296 GT3, four tracks). They are kept
unchanged. The test only asserts that the current loader still accepts the schema, keeps the
boundaries and run counts, and survives a save/load round trip.

Add a file here when a real stored format needs regression coverage, then add its expected track,
boundaries and run counts to the parametrisation in `tests/test_real_data.py`. Keep it small and
remove any personal data first; these files contain no IDs.
