# Development tests

Run from the repository root in the configured virtual environment:

```sh
python -m unittest discover -s tests -t . -v
```

Plain `python -m unittest discover -v` from the root also discovers the package. Individual modules use `python -m unittest tests.test_media_retention -v`. The tests use synthetic fixtures and mocks; do not copy actual camera images, credentials, databases, or logs into this directory. No live camera or SMTP test is launched by test discovery. The reference-server baseline is 188 tests; the reorganized branch must be validated separately before merge.

Phase 1 check: 29 tests in four modules passed locally with both discovery commands. Full 188-test reference-server verification remains required.

Phase 2: six mocked cloud API tests; expected full suite 194. Phase 3a: three new shared relay adapter tests (expected full suite 197), awaiting execution with the real pinned SDK. Run `python -m unittest tests.test_sdk_relay -v` first in a separate worktree using the reference-server virtual environment. The adapter tests make no network calls.
