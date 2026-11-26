# Changelog

This records development milestones, not a published production release.

## Unreleased — 2026-11-26

### Validated on the reference H4 / Ubuntu test server

- 108 unit tests passed with local .env present; credential test isolation fixed (49f6de4).
- Persistent private .env login, mode 600, and UID-based cloud query/device discovery confirmed.
- Cloud device_name returned the app display name; local alias independent of UID.
- Observed login API code 20005 on wrong password. Special automatic retry suspension planned, not implemented.
- Six successful cloud polls with one login and a new event detected without a client-initiated P4P session.
- Three unique same-day cloud-to-SD matches, all at zero offset.
- Three full-resolution SD originals in one relay session; verified MD5 and persisted receipts, repeat download skipped.
- Three separate SMTP emails received, attachment SHA256 identical to SD original; repeated send skipped.
- Single/grouped preview plans confirmed; private grouped live transmission remains untested.

### Implemented

- H4 protocol compatibility and complete KCP receive-queue draining, safe original filenames.
- Persistent SQLite event, download, delivery and route receipts; conservative uncertain-delivery state.
- Per-camera SMTP settings, Revierwelt single-attachment/unique-recipient guard, no mixed-camera batches.
- Commented local TOML configuration and protected literal .env parser.
- Exact UID selection in cloud and SD probes; legacy diagnostic index mode retained.
- Current README separated from historical development log.

### Pending

- Continuous service, persistent cursors, initial-start filtering, retry/recovery, multi-day test, native LXC/systemd and final Revierwelt validation.
- Actual SD transfer through the configured UID path and real multi-camera operation.
- Later WOLFANG WT08-WB (Ucon) and Xega XG-23 (UBox) compatibility tests; separate UBox credentials, backend equivalence unverified.
- Upstream SDK contributions after validation.

See [development history](docs/DEVELOPMENT_HISTORY.md) for detailed earlier experiments and superseded findings.
