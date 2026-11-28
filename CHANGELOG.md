# Changelog

This records development milestones, not a published production release.

## Unreleased — 2026-11-28

### Reference camera identification (documentation correction)

- The owner confirmed DEATTI as the manufacturer and DL04 as the model designation printed on the camera and retail box on 2026-11-26. The earlier `H4` label in the development history refers to this same reference camera; its origin is not established. It must not be presented as a confirmed manufacturer model or hardware designation. No runtime changes or new compatibility claims.

### L3 interim reference test (2026-11-28)

- At 08:26 UTC on the unchanged 163f46b runtime: 975 logged cycles, 12 relay openings, 15 SMTP acceptance entries, queue sent=25 (10 pre-L3), no pending/downloaded/uncertain rows, zero counted cloud/original-retry/SMTP setup/uncertain/service-stop entries. Cloud retry cleared; battery reported 100%, charging=0. External sensor samples during estimated L3 interval ranged from -3.07 to -1.41 C. Interim evidence only; actual inbox receipt, battery endurance and event completeness remain open. See docs/SERVICE.md.

- Subsequent complete supplied-log review confirms L1 recovery episodes and L3 through cycle 977 (15 new events, verified originals and SMTP acceptances, 12 completed relays). Telemetry: 194 local samples, 65 distinct cloud snapshots, all battery=100; charging=0 after first update. Aggregate evidence only; see docs/SERVICE.md. No runtime changes.

### Repository restructuring (development branch)

- Retention R1: shared configurable [retention].automatic_days (90 default, integer 1–3650) for bounded automatic cloud event queries, service original selection and service SMTP selection. Skip expired backlog, keep cursor commit-after-store and fresh installation baseline; no deletion/schema change. Six new tests; owner confirmed 259/259 in 2.136 s at 41b3361. Owner approved expired definitely unsent image deletion, preserving uncertain originals/status until manual resolution, explicit --resend for known successes, metadata age from capture and history per fresh telemetry observation. Those later R2–R4 features remain pending; legacy media cleanup remains unchanged.

- Record further owner decisions: 90-day capture-age boundary on automatic cloud discovery/download/SMTP; stop automatic retries for expired events; explicit manual camera/date-range older-image delivery; configurable 90-day telemetry history; receipt and image retention measured from confirmed SMTP acceptance. Requirements only. Expired unsent/uncertain deletion, manual resend safeguards, telemetry sampling and metadata age reference require review before runtime implementation.

- Record owner-approved configurable retention defaults: 90 days detailed metadata, delivery receipts and automatic SMTP image age, manual older-image delivery, 24 hours post-acceptance local image cleanup, 30 days local logs and three update backups. Permanent image archival deferred to a later release. Requirements only, no runtime changes; discuss unresolved manual delivery and stale state policies before implementation.

- Simplification S1 (owner-approved): replace the fixed-path privileged deployment design with a user-selected single installation directory, optional service account, Linux/Debian 13 reference, manual/file logs or systemd journal, simple install/update/uninstall and optional media backup. Remove superseded root handoff, version-pointer, whole-venv approval, privileged transaction modules and fixed unit/tests. Retain runtime, project wheel and development ZIP verification, dependency pins, config/schema and full-media backup checks. Previous prototype at c895064 remains historical; 340 tests were not run, last verified 328/328 at 4cfbabe. Remove 87 prototype-specific tests (253/253 passed in 2.141 s at 56979da, package/development bundle passed); new scripts/logging/units/optional-media backup remain pending. No active runtime or L3 changes.

- Phase 7b.4b.1: add release_acceptance.py: independently approved release ID/schema-contract/whole-venv SHA256, strict recursive administrator-owned tree metadata and separate readiness marker; candidate readiness requires stopped writers and successful unprivileged config check with unchanged inputs. Bind public production_update to both approved release trees, verified backup schema and unchanged config/credentials, explicit operator review and final pre-switch verification. Run trusted checker source using selected interpreter as service UID/GID (no inherited groups, no root candidate code, no secret output). No activation, first selection or automatic migration. Twelve additional synthetic tests (340 expected), including a real runtime-schema backup and final-gate refusal. Actual distinct identities and trusted provenance remain target gates.

- Phase 7b.4a: add version-1 exact SQLite catalog contract for the six startup and five lazy tables, including autoindexes, user_version/application_id checks and rejection of unknown schema objects; verify a private backup before schema inspection. Offline configuration checker uses existing runtime parsers and explicit protected credential file, no inherited environment fallback, no network, no credential values in output. Fifteen targeted tests passed in 0.055 s and full 328/328 in 2.271 s at 4cfbabe, including direct comparison of literal runtime DDL, actual startup schema and verified backup. No automatic migration, no release-specific approval binding or activation yet.

- Phase 7b.3b.2: add fixed-path mixed-owner offline backup and update composition. Require protected administrator backup parent, exact source UID/GID/modes and regular single-link files, reject unexpected attributes/links and filesystem crossings within state. Keep queue flock; copy stopped DB and committed WAL into private scratch, reconstruct SQLite snapshot there without opening live DB as root, refuse rollback journal; share existing manifest/receipt validation. Integrate marker removal and service stop under deployment lock, explicit external-writer and compatibility callbacks, named layout checks, verified backup and expected-current switch. No activation or state restore. Eleven targeted tests passed in 0.054 s and full 313/313 in 4.648 s at cff4b87, no ResourceWarnings, including same-owner real filesystem/WAL/transaction tests and synthetic ownership checks. No root CLI, actual distinct-owner/systemd validation pending.

- Phase 7b.3b.1: root-only factory for fixed production service control (no privileged CLI). Verify independently approved unit SHA256, administrator file metadata, loaded fragment, no drop-ins/reload needed and expected kill policy; remove only the safe activation marker, stop synchronously and require inactive/dead state, zero main/control PIDs and no reported pending job. No automatic restart, enable/disable/mask or restoration. Twelve synthetic/mock tests passed in 0.007 s, full 302/302 in 2.186 s at 206418f; no real systemd calls. Manual workers, concurrent administrative changes, cgroup emptiness and target property behavior need separate validation. Mixed-owner backup and transaction integration follow.

- Phase 7b.3a: compose offline same-owner update and rollback rehearsal with trusted stop/quiescence/compatibility callbacks, absent activation marker, fresh verified backup, retained queue flock and outer deployment lock, and expected-current comparison inside the atomic pointer lock. No restart or DB restore, no first install or real systemd adapter. Preserve existing backup/switch APIs; thirteen synthetic transaction tests passed in 0.078 s and full 290/290 in 4.431 s at 5282e63, no ResourceWarnings. Production mixed-owner backup, actual service control and compatibility gates remain open.

- Phase 7b.2: add non-root candidate building at the final version path using venv --copies and local wheels, plus an administrator-only library for copying to fresh inodes under a trusted release parent, normalizing modes and retaining the original in quarantine. Reject unsafe types/modes, unexpected links, ownership, filesystem and extended attributes. Preserve the final path, no ready marker or current change. Extend local package check with actual same-owner candidate build/copy/CLI smoke; eleven targeted tests passed in 0.009 s; 277/277 full tests in 2.103 s and package/bundle/staging/handoff verification passed at 2f262a8 (owner output). Privileged orchestration, independent builder quiescence and service-identity validation remain pending; no root CLI.

- Phase 7b.1: define and check selected production filesystem metadata for separated root/service ownership, private state/credentials and absent activation marker, using a trusted synthetic root. Nine targeted tests passed in 0.009 s; full 266/266 passed in 2.094 s at fdc23fe. No privilege changes, service operations or live validation; the contract is not a complete installer or security boundary.

- Phase 7a: document production-readiness gates and introduce a read-only Git-object AST comparison of the original and relocated runtime/diagnostic modules. Normalize only documented import relocations, inventory changed/missing/new definitions and module statements plus top-level import differences. Four synthetic normalization tests included in 257/257 passing tests at 6e468a4 (2.091 s). Audit: 33/39 modules, 147 unchanged normalized definitions, four findings and nine import differences reviewed as intended relocations or credential lookup change. No runtime changes, merge, deployment or live operations.

- Phase 6e: build and verify a local development ZIP with a fixed payload allowlist, project wheel validated against committed export, release-specific README, public templates, selected deployment helpers, project license and SHA256/size manifest with full source commit. No third-party wheels, private files, tests or probes. Extend isolated package check to stage from the verified extracted ZIP. Owner-reported full 253/253 tests in 2.078 s and final package/bundle/staging success message after the 248e49d test instruction; commit was not reprinted. No publication or production activation.

- Phase 6d.3 regression follow-up: owner reported 245 tests in 3.910 s at 0f5386a, FAILED (errors=5), all in existing test_prepare_release.py fixtures. The private-directory guard rejected the fixture root. The earlier package check used umask 077; the direct regression inherited the shell umask. Group-writable directories under umask 002 explain the failure pattern, but the actual server umask has not yet been reported. Create each staging fixture directory explicitly with mode 0700 and assert specific rejection messages to avoid false positives. No runtime or deployment implementation change. Owner confirmed shell umask 0002; at 1b478fa all 20 deployment tests passed under 002/022/077 (0.056/0.055/0.057 s), full 245/245 passed in 3.910 s, no ResourceWarnings. Three expected HTTP fixture warnings.

- Phase 6d.3: add development-only offline backup, verification and inert recovery rehearsal. Require stopped writers and acquire the existing queue lock; use SQLite backup API, retain complete database and receipts, copy private config and media, validate event/receipt consistency and original digests, and record a private SHA256 inventory. No live restoration, path rebasing, service activation or database rewind. Twelve synthetic tests (245 expected), including WAL, locked queue, uncertain delivery, cleanup receipts, tampering and state preservation. Production orchestration and actual recovery remain open.

- Phase 6d.2: prepare new versioned development installations at their final paths using a trusted local wheelhouse, exact dependency versions and a project SHA256 check. Refuse root CLI execution, existing release replacement and untrusted writable installation directories; serialize staging and publish readiness only after installed checks. Never activate or touch private state. Extend package check with real isolated staging and add eight synthetic tests. Owner-reported full package and versioned staging checks passed at df06366, 233/233 tests in 2.046 s. Production install/activation and backup guards still pending.

- Phase 6d.1: introduce operator-owned release-pointer primitives for first selection, update and explicit code-only rollback. Validate identifiers, release readiness and executable, refuse malformed current pointers and use an atomic relative symlink replacement under a pointer lock. Eight synthetic filesystem tests included in 225/225 reference-server tests at c06028a (2.059 s); no production invocation or private state mutation. Installer transaction, stop/backup guards and recovery procedures remain in 6d.2/6d.3.

- Phase 6c: draft guarded systemd service with explicit paths, unprivileged identity, private state, read-only code/config sandbox, restart throttling and SIGINT stop. No automatic cleanup or login resume; no unit installation/start. Add three static contract tests and an offline syntax check with a placeholder executable. Fix an unclosed test fixture connection in test_event_match.py (candidate cause of phase 6b ResourceWarning). Reference-server regression 217/217 passed at 9d933b5 in 3.767 s; no ResourceWarnings. Offline unit syntax verification passed; unrelated XFS CPUAccounting warnings were reported by the host. Actual LXC service validation remains pending.

- Phase 6b: pin direct Pillow requirement and constrain development installs to observed reference versions; separate exact build-tool requirements. Add local wheel content validation and temporary isolated environment build/install, installed import/console checks and full source regression. The reference snapshot is not a hash lock or Debian 13 validation. Reference-server local package checks passed at 063686e: exact versions, KCP source build, 37 runtime files in wheel, 36 installed module imports, console command and 214/214 source tests in 2.049 s. One SQLite ResourceWarning was observed in the test run. No runtime code changes or publication.

- Phase 6a: document deployment and packaging stages, intended runtime/config/state separation, and read-only dependency inventory procedure. Capture actual versions of the working reference environment, including transitive KCP dependencies and build tooling, before selecting exact constraints. Inventory completed: Python 3.14.4, Linux x86_64, SDK 0.1.16, KCP 0.1.6, Pillow 12.3.0, pip check reported no broken requirements (owner-provided output). No host changes.

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

- Record R1 validation (259/259, 2.136 s, 41b3361) and new owner requirement for bounded SMTP backlog throughput. Rate policy and implementation pending approval; no runtime changes.

- Record approved global 30-second image SMTP pacing, no daily limit, oldest eligible first and explicit manual interval override. Record configurable camera connection download-batch requirement; distinguish sequential batches from unverified parallel transfers. Documentation only; restart persistence, configuration scope and controlled batch tests pending review.

- D1: global/per-camera sequential download batch limit (default 3, integer 1–100 experimental); explicit service CLI override; same chosen limit for selection and transfer. Preserve bounded SD window, per-original commits and retry behavior; SMTP image limits unchanged. Three synthetic tests (262 expected), not yet reference-validated. Owner approved SQLite SMTP pacing persistence and alert priority; D2 implementation pending.

- D1 verified 18/18 targeted (0.035 s), 262/262 full (2.154 s), d855099. D2 adds shared persisted SMTP pacing (default 30 seconds, configurable 1–3600), alarm priority, oldest eligible global image selection, one image message per cycle, explicit queue/camera diagnostic override and additive optional schema table. Seven new tests (269 expected), reference pending. No fixed daily limit or independent SMTP timer; manual R4 remains pending.

- D2 validation: owner confirmed 8db4b0d, 55/55 targeted (0.150 s), 269/269 full (2.261 s). R2 cleanup design review pending; no runtime changes.

- R2a: owner-approved hourly/startup cleanup, minimal deduplication protection, 7-day incomplete-download cleanup and manual-only VACUUM design. Implement 24-hour accepted-original cleanup, legacy compatibility, verified pending deletion intent before unlink and reconciliation, backup rejection for unfinished intent. Five tests (274 expected), reference pending. Expired unsent files, metadata/receipt pruning and incomplete attempts pending R2b/R2c.

- R2a verified 41/41 targeted (0.102 s), 274/274 full (2.193 s), fe9a6d2. R2b.1 expires definitely unsent pending/downloaded events strictly older than automatic_days; verified removal intent atomically marks downloaded events expired, retains uncertain originals, retires obsolete download retries/incidents without false recovery, updates backup state checks. Four tests (278 expected), pending reference validation. Metadata and receipt pruning R2b.2 remains open; explicit historical delivery R4 remains open.

- R2b.1 owner verified 47/47 targeted (0.089 s), 278/278 full (2.205 s), 124d2fb. R2b.2 adds independent metadata/receipt age settings (90 days each), safe terminal metadata compaction and atomic detailed receipt retirement, sent_history deduplication marker, backup validation, and startup/hourly pruning. Seven tests (285 expected), reference pending. Unresolved or unreconciled state remains intact; no DDL change or automatic VACUUM.

- R2b.2 verified 47/47 targeted (0.099 s), 285/285 full (2.221 s), b6936e8. R2c adds persistent uncommitted-attempt registration before transfer, atomic receipt/registration completion, and conservative seven-day registered-attempt cleanup, configurable, preserving committed/uncertain and unknown files. Optional download_attempts schema table; six tests (291 expected), reference pending. Legacy unregistered attempts not automatically deleted.
