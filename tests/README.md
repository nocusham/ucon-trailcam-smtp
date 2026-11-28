# Development tests

Run from the repository root in the configured virtual environment:

```sh
python -m unittest discover -s tests -t . -v
```

Plain `python -m unittest discover -v` from the root also discovers the tests. The checkout test package adds src/ to the import path; no installation into the reference-server virtual environment is required. Individual modules use `python -m unittest tests.test_media_retention -v`. The tests use synthetic fixtures and mocks; do not copy actual camera images, credentials, databases, or logs into this directory. No live camera or SMTP test is launched by test discovery. The reference-server baseline is 188 tests; the reorganized branch must be validated separately before merge.

Phase 1 check: 29 tests in four modules passed locally with both discovery commands. All 188 baseline tests are covered by the later successful 197-test reference-server run.

Phase 2: six mocked cloud API tests; expected full suite 194. Phase 3a: three new shared relay adapter tests passed on the reference server (3/3, 0.041 s; owner-reported summary). Full suite: 197/197 passed in 0.273 s on the reference server, at commit `3c8693b` with SDK `0.1.16` (owner-provided terminal summary). This covers phases 1, 2 and 3a; live regression remains pending. Run `python -m unittest tests.test_sdk_relay -v` first in a separate worktree using the reference-server virtual environment. The adapter tests make no network calls.

Phase 3b: three SDK boundary tests in `tests.test_sdk_boundaries` verify the credential and SD re-exports and static direct SDK import confinement. The full 200-test suite passed on the reference server at c93cbf2 in 0.297 s (owner-provided terminal output); the architecture test must be adapted when moving to src/ in phase 4. No live network access is required.

Phase 3c: four tests in `tests.test_runtime_boundaries` cover pure diagnostic import confinement and the extracted legacy SMTP settings reader. Full 204-test suite passed at 7540fd4 in 0.324 s; all nine offline CLI help checks passed (owner-provided output). Run the checks from the separate worktree, without copying private state. Adapt the root-module architecture guards during phase 4.

Phase 4a: one new legacy probe/tool module identity test; architecture guards include tools/. Full 205-test suite passed at 5aadfbf in 0.325 s and all nine legacy CLI help checks passed. The first raw new-tool comparison stopped on argparse's program name and usage wrapping; the other two were not reached. The corrected offline check is `python -m unittest tests.test_cli_help -v`, which compares normalized usage and the exact help body across all three tool pairs. The corrected test passed at 9f9f8cf in 0.584 s (all three pairs). Phase 4a complete; combined 206-test run pending during phase 4b. The runtime remains at the root until phase 4b; keep the active reference checkout unchanged.

Phase 4b: runtime now lives in src/ucon_trailcam_smtp/. Tests use qualified imports and mock paths. Five new package-layout tests cover checkout/installed secret-path behavior, module identity, isolated src imports and six CLI help pairs; 211/211 passed at 9bc9a70 in 2.038 s, along with all nine legacy CLI help checks (owner-provided output). Run full discovery with the existing virtual environment from the separate checkout. The package-only import test uses a temporary working directory and src on PYTHONPATH; it is not a wheel-install test. Actual installation and release artifact validation remain deferred.

Phase 5a: three offline configuration-template tests check parsing, safe defaults, empty credential values using a temporary private file, and relocation. Full 214-test suite passed at cda3649 in 2.033 s (owner-provided output). No real .env or config.local.toml is read.

Phase 5b changes documentation only; no new test count. The next complete run follows source-language review in phase 5c.

Phase 5c: targeted source-language review identified only intentional localization/fixture exceptions; no new tests or code changes. Run the full 214-test suite at the final phase-5 commit to close the checkpoint. Existing tests continue to verify German mail localization.

Final phase-5 regression: 214/214 passed at 46799db in 2.041 s (owner-provided terminal output). Phase 6a requests a read-only reference-environment inventory; do not modify the active L3 virtual environment. Actual isolated installation tests follow in phase 6b.

Phase 6b: run bash deploy/check-package.sh /path/to/reference/python from the separate test worktree. This requires access to the package index or equivalent approved package source, creates a temporary isolated venv, checks a local project wheel and installed CLI/imports, and reruns all 214 tests against a committed source archive using freshly installed reference versions. It does not install into the reference environment or execute live operations. Actual run pending.

Phase 6b result: exact reference dependency installation, KCP native build, local project wheel content/installed smoke checks and 214/214 source tests passed at 063686e in 2.049 s. A SQLite ResourceWarning occurred; phase 6c explicitly closes the test_event_match fixture connection, a confirmed test-only leak and candidate cause. Phase 6c adds three static unit contract tests (217 expected) and deploy/check-systemd.sh for offline syntax validation with a placeholder executable. Run full regression with ResourceWarning enabled and check the log for remaining warnings; no systemd service is started.

Phase 6c result: 217/217 at 9d933b5 (3.767 s), no ResourceWarnings, offline unit syntax passed; unrelated host XFS CPUAccounting warnings. Phase 6d.1 adds eight synthetic release-pointer tests in tests.test_release_layout (225 expected). No real release paths, credentials or state are accessed. Full regression pending.

Phase 6d.1 result: 225/225 passed at c06028a in 2.059 s. Phase 6d.2 adds eight tests in tests.test_prepare_release (233 expected), mocking the installation subprocess. The extended deploy/check-package.sh also stages a real local installation in a temporary versioned directory without selecting it, then runs all source tests with the staged venv. Requires package-index access for the local wheelhouse build; staging itself uses only local wheels. No production state, root rights, or service start. Owner-reported package/staging checks and 233/233 tests passed at df06366 in 2.046 s. Backup/recovery tests follow separately.

Phase 6d.3: twelve synthetic tests in tests.test_state_backup cover SQLite snapshots including committed WAL rows, delivery/uncertain receipts, media integrity, explicit cleanup, private configuration, lock refusal, tampering, path isolation and inert recovery rehearsal. Expected full suite 245. Tests create only temporary fixtures, not real backups; no root, network, or service action. Verification pending.

Phase 6d.3 initial regression: 245 tests in 3.910 s at 0f5386a, five errors in the pre-existing staging fixtures; no reported backup-test errors. Fix explicit private directory modes in tests/test_prepare_release.py and strengthen specific error assertions. The staging and backup modules contain 20 tests combined; run under umask 002, 022 and 077, followed by the full 245-test warning-enabled suite with the original shell umask. Do not change production guards or server permissions. Actual inherited umask and rerun pending.

Phase 6d.3 result: 1b478fa, actual umask 0002, 20/20 deployment tests under each of 002/022/077 (0.056/0.055/0.057 s), 245/245 full tests in 3.910 s, no ResourceWarnings. Three expected HTTP-image fixture warnings. Phase 6e adds eight tests in tests.test_release_bundle (253 expected): strict payload allowlist, stable ZIP for identical inputs, overwrite refusal, missing/symlink input, wheel contents, changed payload, invalid paths/duplicates and commit binding. The extended check-package.sh builds/verifies/extracts a local ZIP and stages from its contents, then runs all source tests in the staged venv. Actual verification pending; no publication.
