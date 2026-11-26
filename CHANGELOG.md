# Changelog

This records development milestones, not a published production release.

## Unreleased — 2026-11-26

### Validated on the reference H4 / Ubuntu test server

- 154 tests passed. Integrated service downloaded two 5120 x 2880 originals in one 8.5-second relay, verified them and subsequently sent two separate STARTTLS emails (both received, two sent events, no second relay). No alarm due; sent-only repeat, continuous operation and real failure paths remain unverified.

- 145 tests passed; live allowlisted telemetry snapshot stored with cloud_activity source and inactivity disabled. Two pending intake photos remain for integration testing.

- 137 tests passed; persistent cloud intake live validated (5/5 and 2/2 cycles across restart, two unique pending events, unchanged startup cutoff).

- Retry-aware UID-selected original download confirmed live (5120 x 2880, 256,172 bytes, 214 blocks, matching MD5, 10.4 s, estimated 601,949 UDP/IP bytes); immediate repeat opened no relay. Live failure path not exercised.

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

- First sequential integrated service with explicit download/image SMTP/alarm SMTP flags, reused device credentials, narrow due-event SD windows across midnight, strict native filename and independent local mail processing during cloud failure. Nine new core tests and 28 existing alarm/intake/telemetry tests passed locally; service entrypoint syntax checked, live SDK/SMTP integration pending.

- Passive cloud telemetry snapshot every 15 minutes and at login; optional per-camera inactivity detection off by default, activity timestamp preferred, conservative photo fallback for models without it. Eight new tests plus twenty existing alarm/intake tests passed locally. Automatic dispatch and actual telemetry CLI validation pending.

- Bounded persistent cloud intake with per-camera startup cutoff/cursor, overlapping catch-up, persistent API backoff and explicit login-block release after code 20005. Nine core tests passed locally; additional HTTP mock test and actual SDK/CLI integration await full server validation. No automatic mail or relay operation.

- Persistent per-event download scheduling, capped exponential backoff and projection of repeated same-event failures into camera alarm state. Explicit --retry-due batch mode; no automatic mail, no extra camera health polling. Eight retry-core and eleven existing alarm tests passed locally; full server integration pending.

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
