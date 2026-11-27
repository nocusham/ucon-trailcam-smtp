# Development tests

Run from the repository root in the configured virtual environment:

```sh
python -m unittest discover -s tests -t . -v
```

Plain `python -m unittest discover -v` from the root also discovers the package. Individual modules use `python -m unittest tests.test_media_retention -v`. The tests use synthetic fixtures and mocks; do not copy actual camera images, credentials, databases, or logs into this directory. No live camera or SMTP test is launched by test discovery. The reference-server baseline is 188 tests; the reorganized branch must be validated separately before merge.

Phase 1 check: 29 tests in four modules passed locally with both discovery commands. All 188 baseline tests are covered by the later successful 197-test reference-server run.

Phase 2: six mocked cloud API tests; expected full suite 194. Phase 3a: three new shared relay adapter tests passed on the reference server (3/3, 0.041 s; owner-reported summary). Full suite: 197/197 passed in 0.273 s on the reference server, at commit `3c8693b` with SDK `0.1.16` (owner-provided terminal summary). This covers phases 1, 2 and 3a; live regression remains pending. Run `python -m unittest tests.test_sdk_relay -v` first in a separate worktree using the reference-server virtual environment. The adapter tests make no network calls.

Phase 3b: three SDK boundary tests in `tests.test_sdk_boundaries` verify the credential and SD re-exports and static direct SDK import confinement. The full 200-test suite passed on the reference server at c93cbf2 in 0.297 s (owner-provided terminal output); the architecture test must be adapted when moving to src/ in phase 4. No live network access is required.

Phase 3c: four tests in `tests.test_runtime_boundaries` cover pure diagnostic import confinement and the extracted legacy SMTP settings reader. Full expected 204-test suite and offline CLI help checks are pending. Run the checks from the separate worktree, without copying private state. Adapt the root-module architecture guards during phase 4.
