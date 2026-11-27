# Changelog

This records development milestones, not a published production release.

## Unreleased — 2026-11-27

### Reference camera identification (documentation correction)

- The owner confirmed DEATTI as the manufacturer and DL04 as the model designation printed on the camera and retail box on 2026-11-26. The earlier `H4` label in the development history refers to this same reference camera; its origin is not established. It must not be presented as a confirmed manufacturer model or hardware designation. No runtime changes or new compatibility claims.

### Repository restructuring (development branch)

- Phase 6a: document deployment and packaging stages, intended runtime/config/state separation, and read-only dependency inventory procedure. Capture actual versions of the working reference environment, including transitive KCP dependencies and build tooling, before selecting exact constraints. Inventory pending; no package, dependency, runtime, systemd or host changes.

- Phase 5c: inspect all 89 Python files for German-language candidates; retain intentional German image subjects and alert emails, MEZ/MESZ, example aliases and synthetic metadata. No runtime or test changes needed in this targeted language review. Record exceptions and scope; final phase-5 reference-server regression 214/214 passed at 46799db in 2.041 s (owner-provided terminal output).

- Phase 5b: translate credentials, health-alert and planned image-footer guides into English; normalize mixed-language headings, update current README status and branch-specific setup instructions, and distinguish historical evidence from current validation. Preserve localized subject/footer examples, technical findings and private state. Documentation only; source-language review follows in phase 5c.

- Phase 5a: move public configuration and credential templates into config/, translate comments into English and update setup commands and links. Active template values are unchanged (static comparison passed), including the example alias. Private configuration locations and runtime code are unchanged. Three new offline template checks; reference-server full suite 214/214 passed at cda3649 in 2.033 s (owner-provided output).

- Phase 4b: move 36 runtime modules to src/ucon_trailcam_smtp, update internal/test imports and mock targets, retain six thin root CLI launchers, and add development-only pyproject metadata. Checkout .env lookup remains at the repository root; an installed package uses explicit secret-file or environment values rather than an implicit file beside installed code. Add five tests for checkout/installed credential lookup, legacy runtime module identity, package-only imports outside the checkout and six normalized CLI comparisons. Reference-server full suite 211/211 passed at 9bc9a70 in 2.038 s and all nine legacy CLI help checks passed (owner-provided output); installed-package validation remains pending. No dependency upgrade, live operations, production installation or release.

- Phase 4a: move the three pure diagnostic implementations unchanged to tools/ and keep thin legacy root launchers with shared module identity. Extend architecture guards to include tools/ and add a legacy import identity test. Reference-server regression at 5aadfbf: 205/205 passed in 0.325 s and all nine legacy CLI help checks passed. The first old/new help comparison stopped on argparse's generated invocation name and usage wrapping; remaining new-tool comparisons were not reached. Add an offline test normalizing only those usage differences while comparing the help body exactly; the corrected test passed at 9f9f8cf in 0.584 s (owner-provided output), covering all three tool pairs. Phase 4a complete; 205 earlier tests plus the new passing test, not a single 206-test run. No runtime changes for this correction. Runtime source and credential lookup unchanged; package relocation follows in phase 4b.

- Phase 3c: move the unchanged legacy read_smtp_settings helper from smtp_probe.py to smtp_settings.py, re-export it from the probe and update queue_smtp.py to import the shared implementation. Add four regression tests for pure diagnostic import confinement, helper identity, settings defaults/password prompting and invalid credentials. Static extraction and import review completed; reference-server full suite 204/204 passed at 7540fd4 in 0.324 s and all nine offline CLI help checks passed (owner-provided output). Prepare phase 4 with explicit attention to source-relative .env discovery. No production state or protocol changes.

- Phase 3b: add narrow credential and SD-card SDK re-export modules and route existing cloud, diagnostic and H4 call sites through them. The existing relay and crypto adapters remain unchanged. No copied SDK implementations, new provider, dependency upgrade, or wire-format changes. One test mock target follows the credential boundary. Three new tests check original SDK object identity and restrict direct SDK imports in root Python modules to four declared boundaries. Static source import review completed; full reference-server suite 200/200 passed at c93cbf2 in 0.297 s (owner-provided terminal output).

- Phase 3a: move the unchanged DiagnosticRelay class and relay_compat context manager from probe.py into sdk_relay.py. The service imports the shared adapter directly; the probe retains its CLI and both helper exports. Add three regression tests for shared identity and SDK patch/output restoration on normal exit and timeout. Static extraction checks passed. Reference-server targeted adapter tests: 3/3 passed in 0.041 s (owner-reported unittest summary). Full reference-server regression: 197/197 passed in 0.273 s at 3c8693b, with SDK 0.1.16 (owner-reported terminal output). Phases 1, 2 and 3a pass automated tests; live regression remains pending. No SDK replacement, protocol or runtime behavior change.

- Phase 2: extract the unchanged REST/account-selection functions and ApiError into cloud_api.py. Service and intake no longer depend on the cloud diagnostic entrypoint, which retains its CLI and helper exports. Six new mocked tests passed locally with a synthetic SDK interface; all six are included in the later successful 197-test reference-server run with SDK 0.1.16. No protocol, configuration, database or retry behavior changes.

- Phase 1: move test modules to `tests/`; extract shared mail construction and sending wrapper from the SMTP probe. Preserve the existing runtime CLI, config/secret discovery and delivery behavior. 29 targeted tests passed locally under umask 002 with both discovery commands; full relocated test suite pending. No production release or merge during L3.
- Reference server D1: 188/188 tests passed with umask 0002; D2: three successful idle cycles. Owner reported six new images sent when installing the camera for L3. L3 is an ongoing unplugged outdoor test, with the supplied solar panel intentionally omitted; battery endurance and data usage are not yet established.

### Sanitized diagnostics (post-soak development)

- D1 reported 183/185 passing with two retention fixture failures. Reproduced both under umask 002; explicit private creation of fixture key/attempt directories fixes the implicit parent-mode issue. Real download root creation now also requests mode 0700 explicitly. Existing permissions and deletion safeguards unchanged. Added three permission regression tests; 17 targeted retention/download tests passed under each of umask 002, 022 and 077 locally. Full 188-test server rerun and D2 pending.

- Added allowlisted cloud failure stages/categories, bounded HTTP/API codes, retry delays and UTC recovery messages; SMTP setup stages and numeric status, conservative uncertain-delivery diagnostics, original retry reasons, alarm/service/retention error categories. No raw exception messages or new network operations. Retry and delivery semantics unchanged. Six standalone diagnostic tests passed locally; four new cloud integration tests and full server suite pending. No retrospective cause assigned to L1 failures.

### Validated on the reference DEATTI DL04 / Ubuntu test server

- 2026-11-27 L1/L2 completion: L1 reached 1,529 cycles (approximately 25.5 hours at nominal cadence; exact elapsed time not independently measured). Latest cumulative L1 counters: six relay openings, six SMTP acceptances, ten sent events total and three previously documented recovered cloud failures. The owner confirmed all six new messages arrived. L2 completed three cycles with zero failures, relay openings or sends; final queue remained sent=10. Cursor continuity and telemetry refresh observed. Outage-time photo completeness and sustained failure recovery remain unverified. See SERVICE.md for evidence limits. Documentation only.

- 2026-11-27 L1 interim: cycle 969 (approximately 16.1 hours at nominal cadence), four relay openings and four new SMTP acceptances, eight sent queue entries total and no other states. Three isolated cloud failures (cycles 99, 188, 219) each recovered after one skipped polling cycle, with catch-up windows of 480 seconds followed by normal 360-second windows. Retry state returned to zero. USB-powered camera, no battery-life claim. Root causes, outage-time photo completeness and full soak/restart acceptance remain unverified. See SERVICE.md. Documentation only.

- 175 tests passed; retention preview reported zero eligible originals, no file changes. Actual old-file deletion remains synthetic-test validated only. Documented 24-hour reference-server soak procedure before repository packaging/LXC transition.

- 167 tests passed; normal SMTP path after retry refinement live validated (4/4 cycles, one original and SMTP acceptance with configured camera alias and local capture-time subject, three idle cycles without relay, no alarms). Actual transport faults were simulated only.

- Integrated ten-cycle run completed 10/10 without failures; one new original (5120 x 2880, 264,906 bytes) in one 9.3-second relay, one new accepted SMTP message, nine idle cycles without relay, no alarms and three sent events without duplicates.

- 154 tests passed. Integrated service downloaded two 5120 x 2880 originals in one 8.5-second relay, verified them and subsequently sent two separate STARTTLS emails (both received, two sent events, no second relay). No alarm due; sent-only repeat, continuous operation and real failure paths remain unverified.

- 145 tests passed; live allowlisted telemetry snapshot stored with cloud_activity source and inactivity disabled. Two pending intake photos remain for integration testing.

- 137 tests passed; persistent cloud intake live validated (5/5 and 2/2 cycles across restart, two unique pending events, unchanged startup cutoff).

- Retry-aware UID-selected original download confirmed live (5120 x 2880, 256,172 bytes, 214 blocks, matching MD5, 10.4 s, estimated 601,949 UDP/IP bytes); immediate repeat opened no relay. Live failure path not exercised.

- Authenticated DEATTI DL04 device-list schema includes integer dynamic_info.latest_active_utc, battery, signal, online_state and power flags. A subsequent live PIR test confirmed that latest_active_utc uses Unix seconds and updated ten seconds after the new event without opening the app or initiating P4P. Periodic contact without PIR and long-term reliability remain unverified; no individual telemetry values or private identifiers recorded here.

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

- Optional local original retention (off by default, 30 days from SMTP acceptance), standalone preview/apply and hourly opt-in service cleanup. Only verified sent originals under managed root; preserves deduplication receipts. Eight local tests passed; reference-server integration pending. Documented repository production/test separation plan for LXC transition.

- Proven pre-submission SMTP setup failures restore downloaded state and persist per-camera exponential retry cooldown (5–60 minutes). Ambiguous submissions remain uncertain; QUIT failure after acceptance no longer blocks delivery. Seven transport/SQLite tests passed locally; two additional queue integration tests pending server validation.

- Configured-camera image subjects now use UCON, local profile alias, capture date/time in Europe/Berlin with MEZ/MESZ; grouped subjects include count and capture-time range. Attachment bytes and basename unchanged; legacy unconfigured subjects unchanged. Four subject-helper tests passed locally, including DST ambiguity; full routing suite and live delivery pending.

- First sequential integrated service with explicit download/image SMTP/alarm SMTP flags, reused device credentials, narrow due-event SD windows across midnight, strict native filename and independent local mail processing during cloud failure. Nine new core tests and 28 existing alarm/intake/telemetry tests passed locally; service entrypoint syntax checked, live SDK/SMTP integration pending.

- Passive cloud telemetry snapshot every 15 minutes and at login; optional per-camera inactivity detection off by default, activity timestamp preferred, conservative photo fallback for models without it. Eight new tests plus twenty existing alarm/intake tests passed locally. Automatic dispatch and actual telemetry CLI validation pending.

- Bounded persistent cloud intake with per-camera startup cutoff/cursor, overlapping catch-up, persistent API backoff and explicit login-block release after code 20005. Nine core tests passed locally; additional HTTP mock test and actual SDK/CLI integration await full server validation. No automatic mail or relay operation.

- Persistent per-event download scheduling, capped exponential backoff and projection of repeated same-event failures into camera alarm state. Explicit --retry-due batch mode; no automatic mail, no extra camera health polling. Eight retry-core and eleven existing alarm tests passed locally; full server integration pending.

- Optional independent TLS alarm SMTP profile, persistent login/API/per-camera incidents, delayed reminders, recovery and rate-limited failed alert retries; 11 standalone tests passed locally. Manual alert test available; automatic health checks and dispatch not integrated yet.

- DEATTI DL04 protocol compatibility (historical `h4_*` module names) and complete KCP receive-queue draining, safe original filenames.
- Persistent SQLite event, download, delivery and route receipts; conservative uncertain-delivery state.
- Per-camera SMTP settings, Revierwelt single-attachment/unique-recipient guard, no mixed-camera batches.
- Commented local TOML configuration and protected literal .env parser.
- Exact UID selection in cloud and SD probes; legacy diagnostic index mode retained.
- Current README separated from historical development log.

### Pending

- Reviewed mahumadad/ubox-p4p at `6f9f87fc31da4eb86531a81b08b3b1ffa4db5fa8`: matching REST routes, distinct UBox portal/app context, shared P4P codec ancestry via the pinned SDK, transport differences that may help diagnose relay stalls, and open SD retrieval / Xega 4G compatibility issues. Added [UBOX_RESEARCH.md](docs/UBOX_RESEARCH.md) with source links, provider-isolation design and staged WOLFANG/Xega tests. Documentation only; no model compatibility or causal fix claimed.

- User-approved restructuring requirement: English throughout the maintained repository and GitHub presentation (documentation, code, configuration comments, CLI/help/logs, tests, deployment and release material). Preserve deliberate user-facing localization and existing behavior; review before production release. See [REPOSITORY_LAYOUT.md](docs/REPOSITORY_LAYOUT.md). No runtime changes during the soak test.

- User-approved future feature, after the existing milestones: optional per-camera image footer on a derived SMTP attachment, with configured camera alias, event battery percentage and local capture date/time. Extend the canvas downwards; no overlay, cropping or resizing of the original photo. Keep the downloaded JPEG byte-for-byte intact. Specification: [IMAGE_FOOTER.md](docs/IMAGE_FOOTER.md). Documentation only during the active soak test.

- Monitor actual failed downloads of known outstanding cloud events, not camera polling. Implement optional per-camera seven-day inactivity warning off by default, using latest_active_utc on DEATTI DL04 and no-photo-event fallback for models without the field. The alert label now says original download rather than camera connection; event-level integration is pending.

- Continuous service, persistent cursors, initial-start filtering, retry/recovery, multi-day test, native LXC/systemd and final Revierwelt validation.
- Actual SD transfer through the configured UID path and real multi-camera operation.
- Later WOLFANG WT08-WB (Ucon) and Xega XG-23 (UBox) compatibility tests; separate UBox credentials, backend equivalence unverified.
- Upstream SDK contributions after validation.

See [development history](docs/DEVELOPMENT_HISTORY.md) for detailed earlier experiments and superseded findings.
