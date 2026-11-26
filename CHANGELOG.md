# Changelog

This records development milestones, not a published production release.

## Unreleased — 2026-11-26

### Validated on the reference H4 / Ubuntu test server

- Authenticated H4 device-list schema includes integer dynamic_info.latest_active_utc, battery, signal, online_state and power flags. A subsequent live PIR test confirmed that latest_active_utc uses Unix seconds and updated ten seconds after the new event without opening the app or initiating P4P. Periodic contact without PIR and long-term reliability remain unverified; no individual telemetry values or private identifiers recorded here.

- Independent alarm SMTP test accepted and received. Full expanded test-suite result not yet reported.

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

- Optional independent TLS alarm SMTP profile, persistent login/API/per-camera incidents, delayed reminders, recovery and rate-limited failed alert retries; 11 standalone tests passed locally. Manual alert test available; automatic health checks and dispatch not integrated yet.

- H4 protocol compatibility and complete KCP receive-queue draining, safe original filenames.
- Persistent SQLite event, download, delivery and route receipts; conservative uncertain-delivery state.
- Per-camera SMTP settings, Revierwelt single-attachment/unique-recipient guard, no mixed-camera batches.
- Commented local TOML configuration and protected literal .env parser.
- Exact UID selection in cloud and SD probes; legacy diagnostic index mode retained.
- Current README separated from historical development log.

### Pending

- Monitor actual failed downloads of known outstanding cloud events, not camera polling. Implement optional per-camera seven-day inactivity warning off by default, using latest_active_utc on H4 and no-photo-event fallback for models without the field. The alert label now says original download rather than camera connection; event-level integration is pending.

- Continuous service, persistent cursors, initial-start filtering, retry/recovery, multi-day test, native LXC/systemd and final Revierwelt validation.
- Actual SD transfer through the configured UID path and real multi-camera operation.
- Later WOLFANG WT08-WB (Ucon) and Xega XG-23 (UBox) compatibility tests; separate UBox credentials, backend equivalence unverified.
- Upstream SDK contributions after validation.

See [development history](docs/DEVELOPMENT_HISTORY.md) for detailed earlier experiments and superseded findings.
