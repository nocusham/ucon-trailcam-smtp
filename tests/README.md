# Development tests

Run from the repository root in the configured virtual environment:

```sh
python -m unittest discover -s tests -t . -v
```

Plain `python -m unittest discover -v` from the root also discovers the package. Individual modules use `python -m unittest tests.test_media_retention -v`. The tests use synthetic fixtures and mocks; do not copy actual camera images, credentials, databases, or logs into this directory. No live camera or SMTP test is launched by test discovery. The reference-server baseline is 188 tests; the reorganized branch must be validated separately before merge.

Phase 1 check: 29 tests in four modules passed locally with both discovery commands. Full 188-test reference-server verification remains required.
