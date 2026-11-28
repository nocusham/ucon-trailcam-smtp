# ucon-trailcam-smtp

Experimental self-hosted SMTP bridge for Ucon 4G trail cameras, using original SD-card images without modifying camera firmware. The UBIA backend is still required for authentication, event discovery and relay connectivity. Paid cloud storage is not intended; service entitlement and long-term availability are not guaranteed.

**Reference camera: DEATTI DL04.** Manufacturer and model designation confirmed by the owner on both the camera and its retail box on 2026-11-26. Earlier development notes use the label `H4`; its origin and status as a vendor or internal hardware designation are unverified. In this repository it refers to the same reference test camera, not a separately validated model. Existing `h4_*` compatibility module names are retained for now.

**Development status (2026-11-27):** the DEATTI DL04 reference camera's cloud discovery, SD original download and SMTP delivery are live-tested. The reference-server soak run reached 1,529 cycles; six new SMTP acceptances and six relay openings were reported in the latest cumulative counters, all six messages were confirmed received by the owner, and three transient cloud failures recovered automatically. The process restart completed 3/3 cycles without error, relay or resend; the queue remained at ten sent events. Sustained outages, actual SMTP/SD failure recovery and production deployment remain pending. Do not treat this version as an unattended production release.

## Current status

| Component | Status |
| --- | --- |
| Python / SDK | Python 3.14.4 on Ubuntu test server; SDK 0.1.16 pinned |
| Unit tests | 253/253 passed at 56979da (2.141 s), package/development bundle check passed; live regression pending |
| Ucon cloud event query | Live confirmed, no client-initiated P4P session |
| Cloud watch | 6/6 successful polls with one login; new event and duplicate detection confirmed |
| Camera selection | Exact UID from enabled local camera profile; live cloud query and relay credential discovery confirmed |
| Cloud camera name | Server API returned the configured app display name; local alias remains independent |
| SD matching | Three same-day cloud events matched DEATTI DL04 PIR stills with zero offset |
| Original download | Three 5120 x 2880 JPEGs in one 10.3 s relay session; all MD5 checks passed |
| SQLite | Persistent event identity, downloaded/sent states and receipts; no duplicate download or send in repeat tests |
| SMTP single | Three separate messages received on private TLS server; received attachment SHA256 exactly matched the SD original |
| SMTP grouped | MIME preview confirmed; real grouped delivery not tested |
| Camera-specific SMTP | Live single-camera preview; distinct two-camera routes tested synthetically |
| Credentials | Private .env loaded successfully without exported credentials; mode 600 confirmed |
| Continuous service / retry | Integrated; normal reference-server soak and restart validated; sustained failure recovery pending |
| Proxmox LXC / systemd | Deferred until application validated |
| Revierwelt | Single-image guard implemented; live delivery deferred |

The DEATTI DL04 works with a personal SIM in the reference tests. Cloud event type 1 is a candidate for DL04 PIR stills (SD event type 4, photo length 65535); do not generalize to other models without validation. Remote deletion is not implemented. Actual SIM billing, extended sleep behavior, event availability latency, pagination, entitlement and long outage recovery remain unverified.

## Installation and local configuration

The owner-approved deployment design uses a single freely chosen installation directory (default `~/ucon-trailcam-smtp`), optional service account, manual or systemd user/system operation and no root requirement for application installation. See [current deployment architecture](deploy/README.md). The simplified install/update/uninstall scripts are not implemented yet; the following are development-checkout instructions only.

These source-checkout instructions describe the restructuring branch, not a production release. Select the branch explicitly in a new development checkout; never switch the active L3 checkout. The default main branch still uses its historical root templates.

Linux, Python 3.12+ as required by the pinned SDK; use a private checkout and an unprivileged user. For current development stay on the existing Ubuntu test server. Do not create the production LXC yet.

```sh
git clone https://github.com/nocusham/ucon-trailcam-smtp.git
cd ucon-trailcam-smtp
git switch refactor/repository-layout
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -t . -v
umask 077
test -e .env || cp config/.env.example .env
test -e config.local.toml || cp config/config.example.toml config.local.toml
chmod 600 .env config.local.toml
nano .env
nano config.local.toml
```

For an inactive development checkout, review changes before updating and rerun tests. Never update the active L3 checkout. Do not overwrite existing local configuration. The annotated English template [config.example.toml](config/config.example.toml) explains every field. See [credential setup](docs/CREDENTIALS.md) for literal KEY=value syntax, password sources, file ownership and restart behavior. File values override existing environment variables; never source the .env as shell code. Use a separate password entry for each private SMTP credential as needed. Only the public Revierwelt password "mail" is permitted directly in the profile, restricted to the known server and recipient domain. The test suite must never read the real credential file. Earlier credential assertions were fixed in commit 49f6de4; any exposed password should be rotated.

Each camera profile has an independent UID, enabled flag and SMTP host, port, security, sender, recipient, username, password reference, mode and limit. Names are local aliases, not account device indices. Configured-camera image subjects use `UCON testkamera - 15.01.2026 14:52:05 MEZ` (capture date/time in Europe/Berlin with MEZ/MESZ, not server or delivery time). Grouped subjects also include the number of originals and their capture-time range. Original attachment names and bytes are unchanged. Legacy unconfigured SMTP probes retain their original subjects. No fallback to a global destination. Revierwelt requires a distinct recipient for each camera and one attachment per message. Private destinations may use grouped mode, but never mix images from different cameras. One recipient per camera is currently supported. Use STARTTLS or implicit TLS with certificate verification for private mail. Revierwelt's TLS support is not confirmed.

## Manual diagnostic workflow (historical reference tests)

Examples use the configured alias `testkamera`, replace it locally. All commands below assume an activated virtual environment. Never publish real UIDs, account names, passwords, signed URLs, packet captures, private images or database contents.

### 1. Login and device discovery

```sh
python cloud_probe.py --config config.local.toml --camera testkamera --hours 24
python probe.py --config config.local.toml --camera testkamera
```

These commands authenticate, verify the selected UID, and (first command only) query cloud events. Neither initiates P4P or SMTP. Legacy index-based diagnostics are still available but must not be used for automatic multi-camera routing. The device-list response includes device_name; use the local profile's UID for identity. A dedicated device discovery CLI is planned, not implemented.

### 2. Bounded cloud watch and SQLite queue

```sh
python cloud_probe.py --config config.local.toml --camera testkamera \
  --watch --hours 24 --cycles 6 --interval 60 --overlap 300 \
  --queue-db data/events-watch-test.sqlite3
```

The first poll scans 24 hours, subsequent polls overlap the last successful end by five minutes. HTTP 401/403 resets the cloud session; other API errors use bounded backoff. Cursor is currently in memory only. No image downloads or SMTP. Database keys are camera_uid + itemid. This is a historical test queue: never promote it into a production queue or blindly deliver historical events.

### 3. Match SD events and download originals

Choose a calendar day containing known test events; examples refer to the validated reference test day. The camera may wake and consume mobile data; close the app and do not run concurrent camera clients.

```sh
python probe.py --config config.local.toml --camera testkamera \
  --events --day 2026-11-26 --sd-flow app \
  --match-queue data/events-watch-test.sqlite3
# Create a NEW test copy only; do not overwrite or reset existing batch DB.
sqlite3 data/events-watch-test.sqlite3 ".backup data/events-batch-test.sqlite3"
chmod 600 data/events-batch-test.sqlite3
python probe.py --config config.local.toml --camera testkamera \
  --events --day 2026-11-26 --sd-flow app \
  --download-queue data/events-batch-test.sqlite3 --batch-limit 3 \
  --output-dir media/batch-test
```

Matching is unique within ±2 seconds, excluding SD network-wake type 3. No thumbnail fallback. Each complete original is checked against metadata MD5, fully decoded and saved with a safe native basename where available. SHA256, size and dimensions are committed with the downloaded state. On a repeated run verified already-downloaded files are skipped. The configured UID login/discovery and actual SD transfer are live-confirmed. Legacy app-flow batch transfer itself is live-confirmed.

### 4. Camera-specific SMTP preview and explicit send

```sh
python camera_smtp.py --config config.local.toml \
  --queue-db data/events-batch-test.sqlite3 --day 2026-11-26
```

Without --send: local validation only. The --preview-sent option previews already delivered images and cannot be combined with --send. To test actual delivery of new downloaded images only, add --send and keep the private TLS test recipient. No Revierwelt live test yet. Do not reset sent states. The older queue_smtp.py global sender refuses a multi-camera database.

```sh
sqlite3 -readonly data/events-batch-test.sqlite3 \
  'SELECT state,count(*) FROM events GROUP BY state;'
```

States: pending (awaiting original), downloaded (verified original), uncertain (committed before SMTP), sent (SMTP helper returned successfully). SMTP acceptance is not proof of inbox delivery; on an unclear outcome the affected message is not automatically resent. Grouped messages commit all associated states together. A route receipt records the destination used, not passwords. Prior uncertain delivery blocks that camera; newly uncertain delivery stops the invocation. No automated resolution or retry yet. SMTP image loader limit is 8 MiB; SD downloader limit 16 MiB. No resizing or silent fallback.

## Protocol findings and measured reference results

The compatibility layer tested with the DEATTI DL04 (historical `h4_*` module names) corrects P4P tail permutations, outbound KCP encoding, relay conversation selection, native RDT framing and KCP receive-queue draining, without modifying installed SDK or camera firmware. The app SD flow stops the live stream before photo transfer. The production image source is the SD original, not the cloud snapshot. Cloud preview retrieval is development-only.

| Test | Result |
| --- | --- |
| Cloud snapshot | 640 x 360 JPEG, 5,948 bytes |
| SD listing and matching | 6.9 s, 103,460 estimated server IPv4/UDP bytes |
| Z12 single original | 247,692 bytes, 7.6 s, 537,551 estimated server IPv4/UDP bytes |
| B1 three originals | 763,883 JPEG bytes total, 638/638 blocks, 10.3 s, 1,235,998 estimated server IPv4/UDP bytes |

These are server-side measurements, not SIM billing or independent controlled comparisons. Intermittent initial settings ACK failures are still possible.

## Optional error notification channel

An independent TLS SMTP account and private recipient can be configured in [alerts] / [alerts.smtp]. Defaults: login 15 minutes, API 30 minutes, repeated failed SD-original downloads of known outstanding cloud events 24 hours, repeat reminder 24 hours, alarm SMTP retry 60 minutes and optional recovery notice. Disabled by default. Persistent incident and notification state logic exists; automatic health observation/dispatch is not yet wired into the continuous service. No extra active camera reachability probes. Optional per-camera inactivity detection after seven days without reported activity is implemented in the bounded cloud test, disabled by default; automatic mail dispatch remains pending. The DEATTI DL04 device-list field dynamic_info.latest_active_utc is a plausible UTC Unix timestamp in seconds and updated ten seconds after a new PIR photo in a live test without an app or client P4P session. Periodic status reports without PIR remain unverified. For models without this field, a no-photo-event warning is the planned fallback. The manual alert test was accepted and received on the reference server. Manual configuration check and explicit test:

```sh
python health_alerts.py --config config.local.toml
python health_alerts.py --config config.local.toml --send-test
```

The second command requires enabled=true and a configured private alert destination. No camera/cloud activity or queue updates. See [health alert configuration and semantics](docs/ALERTS.md).

## Retry-aware original download test

Optional [download_retry] in the local TOML sets initial_minutes=5 and max_minutes=360. Use the existing configured SD batch command with the additional --retry-due flag. The SQLite register persists next due time and actual failures per pending photo. A bounded batch with no due originals skips the relay; actual list/transfer timeouts and missing/ambiguous matches are recorded, other exceptions are not yet classified. A confirmed repeated failure of the same outstanding event spanning the camera alarm threshold creates a per-camera incident. No email is sent in this manual test. A different successful photo cannot clear older failed pending originals. Eight new retry-core tests and eleven existing alarm tests passed locally; full CLI/SDK path and server suite still require validation. See [ALERTS.md](docs/ALERTS.md).

## Persistent cloud intake test

The live retry-aware SD batch downloaded one 5120 x 2880 original (256,172 bytes, 214/214 blocks, matching MD5, safe camera basename) in 10.4 seconds, with estimated server IPv4/UDP traffic of 601,949 bytes. Repeating the batch immediately selected zero due items and opened no relay. No confirmed failure in that live run.

New bounded cloud_intake.py test uses an independent new database. It records a per-camera startup cutoff (no historical event import), a persisted overlapping cursor (five minutes) and one-hour forward catch-up steps. Events commit before the cursor, so a replay after interruption is deduplicated. DEATTI DL04 candidate photo type 1 only. One account login reused per invocation. HTTP 401/403 resets the session; other errors get persisted backoff (up to 15 minutes). A confirmed login-stage API code 20005 persists a login block; correct credentials and explicitly use --resume-login with the same database. No credential hashes stored. Legacy probes remain manual and do not enforce this block. Only bounded intake is enabled, no P4P or mail. Current implementation stops the remaining cameras in a cycle after an API error; multi-camera fault isolation, pagination, long-gap completeness and periodic device telemetry are still pending.

```sh
python cloud_intake.py --config config.local.toml --queue-db data/events-intake-test.sqlite3 --cycles 3 --interval 60
```

Use a fresh path for the first run, never an old historical or production queue. Trigger a new PIR after the start, then repeat against the same path to check the persisted cursor. Nine core tests with synthetic API/store and real SQLite passed locally. One additional HTTP mock test checks structured login errors; full SDK/CLI and real cloud test are pending.

## Passive telemetry test

Persistent intake was live-validated (137 tests passed, 5/5 then 2/2 successful cycles, two distinct pending events, unchanged startup cutoff). It now stores allowlisted latest telemetry per enabled camera in camera_telemetry at login and every 15 minutes using the same authenticated cloud session. Per-camera optional inactivity_warning=false and inactivity_days=7 (1–365) precede [cameras.smtp]. Two fresh stale observations prepare a separate inactivity incident. The fallback for cameras lacking the field starts only with current photo queries and resets after observation gaps; model compatibility and API completeness remain unverified. Invalid/missing known activity metadata never means offline. No P4P or mail in this test; automatic dispatch must explicitly gate inactivity on fresh cloud observations. Eight new tests and twenty existing alarm/intake tests passed locally. See [ALERTS.md](docs/ALERTS.md).

## Integrated service (reference-server test)

The first sequential service is implemented in trailcam_service.py; see [SERVICE.md](docs/SERVICE.md) for staged tests and explicit action flags. It reuses the authenticated device response for due SD-original batches, requires the original camera filename, closes relays before SMTP and independently processes existing downloads and due alarms even if cloud login is blocked. Default one cycle; --loop is explicit. The first integrated reference-server test passed: 154 tests, two original photos in one 8.5-second relay, two separate emails received, both events committed as sent. A subsequent ten-cycle run completed without errors, detected one new photo, opened one 9.3-second relay, accepted one new SMTP message and retained three sent events without duplicates. Nine idle cycles opened no relay. Long-duration and actual fault validation remain pending; do not deploy unattended yet.

## Known API errors and recovery plan

| Observation | Implemented now | Planned service behavior |
| --- | --- | --- |
| Login API code 20005 after deliberately wrong password | Structured error; persistent block in bounded intake | Integrate same block into full service; explicit resume after correcting credentials; existing verified files may still be sent |
| HTTP 401/403 during watch | Drop session and authenticate next attempt | Bounded reauthentication |
| Other cloud/network errors | Bounded watch backoff | Persistent cursor, capped backoff and recovery |
| Camera/SD failure | Manual test fails; committed files retained | Per-camera persistent retry policy |
| SMTP outcome uncertain | Retain uncertain, no automatic resend | Explicit safe resolution, distinguish known pre-send failures |

Code 20005 is observed for a wrong password, not a proven exhaustive vendor error mapping. The login-specific retry suspension is implemented in the bounded persistent intake test, not yet in the full service.

## Roadmap

Completed development milestones and remaining validation gates are distinguished below. See the restructuring section and [service evidence](docs/SERVICE.md) for the latest test results.

- [x] DEATTI DL04 original transfer, cloud event intake, matching, persistent file receipt and SMTP test.
- [x] Per-camera SMTP profiles, protected credentials, UID-based cloud and device discovery.
- [x] Isolate credential tests from local .env; 108 tests confirmed.
- [ ] Integrate UID-based real SD transfer and multi-camera processing on the current server.
- [x] Implement optional independent alarm SMTP configuration and persistent incident notification core (11 local tests).
- [x] Validate manual alert SMTP live (test mail received).
- [x] Integrate observation/dispatch and optional inactivity state into the service, without extra active camera checks; live automatic alert delivery remains pending.
- [x] Persistent download retry core with explicit retry-aware SD batch test (core tested locally; live integration pending).
- [x] Persistent intake cursor, startup cutoff, bounded catch-up and login-specific retry block in bounded test (nine core tests).
- [x] Validate normal bounded intake and integrate service processing; freshness/pagination and automatic alert delivery still require live validation.
- [x] Integrate continuous service, retry handling and optional retention; sustained outage, multi-camera isolation and actual deletion tests remain pending.
- [ ] Device discovery helper; do not auto-enable newly discovered cameras.
- [ ] Test wake after extended idle, event reliability, mobile data use, pagination and service entitlement.
- [x] Nominal 24-hour soak run (1,529 cycles), recipient confirmation and three-cycle process restart test on the existing Ubuntu reference server; longer field validation remains open.
- [ ] Restructure the repository for production/test separation and use English consistently throughout the maintained project, including documentation, code, configuration comments, CLI help, logs, tests and deployment files; see [repository layout and language policy](docs/REPOSITORY_LAYOUT.md).
- [ ] Native unprivileged Debian 13 LXC, systemd autostart and actual reboot test.
- [ ] Final Revierwelt delivery test with one original per message.
- [ ] After completion of the existing goals: optional per-camera image footer appended below the complete original image, never overlaid on it; see [planned image footer](docs/IMAGE_FOOTER.md).
- [ ] After first live system: validate WOLFANG WT08-WB (Ucon) and real multi-camera operation.
- [ ] Afterwards investigate Xega XG-23 (UBox), with separate account authentication, provider-scoped failure handling and a validated SD-original transfer. See [UBox research and camera compatibility test plan](docs/UBOX_RESEARCH.md); compatibility is unconfirmed.
- [ ] Discuss small upstream SDK fixes with the maintainer after application validation; clarify licensing before redistribution.

## Documentation

- [Annotated camera configuration](config/config.example.toml)
- [Credential setup](docs/CREDENTIALS.md)
- [Optional health alerts](docs/ALERTS.md)
- [Deferred native Proxmox LXC plan](docs/LXC.md)
- [Planned optional image footer](docs/IMAGE_FOOTER.md)
- [UBox protocol research and additional-camera test plan](docs/UBOX_RESEARCH.md)
- [Full historical development and protocol analysis](docs/DEVELOPMENT_HISTORY.md)
- [Development changelog](CHANGELOG.md)

References: [p4p_camera_sdk](https://github.com/ArtemKiyashko/p4p_camera_sdk) (pinned 0.1.16), [ubox-p4p](https://github.com/mahumadad/ubox-p4p) (related protocol research, not validated as a substitute). Unofficial project; not affiliated with Ucon, UBIA or Revierwelt. No vendor firmware, private captures or personal images bundled.

### SMTP setup retry

A typed SafeSMTPFailure is emitted only for failures before smtplib.send_message is invoked (connection, TLS, authentication). The verified original remains downloaded; the unsubmitted receipt is rolled back atomically with a per-camera cooldown persisted in smtp_retries (5, 10, 20, 40, then 60 minutes maximum). No retry after ambiguous submission; uncertain state still requires manual review. Once SMTP accepts the message, a subsequent QUIT failure does not undo acceptance. Explicit negative replies within send_message are still conservatively treated as uncertain in this implementation. Successful delivery clears the retry cooldown. No new config required; no SMTP-specific alarm category yet. See SERVICE.md. Seven isolated transport/SQLite tests passed locally; two queue integration tests await full server suite.

### Local image retention

Optional [retention] enabled=false, days=30 (1–3650). Age is measured from confirmed SMTP acceptance, not capture time. Preview with media_retention.py --config CONFIG --queue-db DB --output-dir MEDIA (no --apply). Actual removal requires enabled=true plus --apply, or --cleanup on the service (first cycle and hourly thereafter). Only state=sent with accepted receipt and verified hash/size in the managed output directory qualifies; unknown, unsent, uncertain, changed, shared or symlinked files are retained. Event, download and delivery receipts are retained permanently; media_cleanup logs successful file removals. Camera SD cards are not touched. A crash between unlink and audit commit can leave a missing file without a cleanup record, reported as skipped; never reset sent state. Preview of old sent messages may no longer work after removal. 175/175 reference-server tests passed, including synthetic deletion tests; read-only preview found zero eligible originals. Automatic hourly cleanup remains unverified on the server.

Repository packaging and production/test separation are planned for the LXC transition; see [repository layout](docs/REPOSITORY_LAYOUT.md).

The reference-server soak and process restart runs are complete with the existing test database, private SMTP and cleanup disabled. See [final results](docs/SERVICE.md#l1-and-l2-final-results-2026-11-27). All six new L1 messages were confirmed received. L1/L2 used USB power. L3 continues on the separate reference checkout without the supplied solar panel; battery endurance and SIM data consumption are not yet established. Sanitized diagnostics and the restructuring branch have passed automated regression; versioned packaging, live regression and LXC validation remain pending. Resolve SDK licensing before public production distribution.

## Repository restructuring (development branch)

Phases 1 and 2 separate synthetic tests from runtime modules and extract shared mail and cloud REST functions (`mail_message.py`, `cloud_api.py`). Phase 3a extracts the shared relay adapter into `sdk_relay.py`, so the service no longer imports the diagnostic probe. The existing SDK and relay behavior are retained. All three new adapter regression tests passed on the reference server (0.041 s); the full 197-test suite passed on the reference server (0.273 s) at 3c8693b with SDK 0.1.16, covering phases 1, 2 and 3a. Live regression remains pending. Phase 3b isolates credential and SD-card SDK imports in `sdk_credentials.py` and `sdk_sdcard.py`; `sdk_relay.py` and `h4_crypto.py` remain the relay and crypto boundaries. All 200 tests passed on the reference server at c93cbf2 (0.297 s). Phase 3c extracts the shared legacy SMTP settings reader into `smtp_settings.py`, removes the final direct import of a pure diagnostic probe from runtime-capable root modules, and adds four tests (204 expected). The full 204-test suite passed at 7540fd4 (0.324 s), and all nine legacy CLI help checks passed. Phase 4a moves the three pure diagnostic implementations to tools/ and keeps root compatibility launchers; see [manual tools](tools/README.md). All 205 tests passed at 5aadfbf (0.325 s), as did all nine legacy CLI help checks. The initial new-tool help comparison stopped at the first tool because argparse displays the module invocation name and wraps usage differently. A new offline test compares normalized usage and the unchanged help body for all three tools; the corrected test passed at 9f9f8cf in 0.584 s, covering all three tools. Phase 4a is complete with 205 previous passing tests and one additional passing test; the combined 206-test suite has not yet been run in a single invocation. Phase 4b moves the runtime into `src/ucon_trailcam_smtp/` and introduces development-only packaging metadata (`0.0.0.dev0`). Six runtime CLI launchers at the root preserve existing commands; tools and tests import the namespaced package. From a source checkout, the implicit `.env` remains at the repository root. An installed package does not search for an implicit `.env`; use an explicit protected `UCON_SECRETS_FILE` or environment values. The full 211-test suite passed at 9bc9a70 in 2.038 s, along with all nine legacy CLI help checks. Phase 5a moves the two public example templates into config/ and translates their comments without changing active values; see [configuration templates](config/README.md). The three new template tests are included in the successful 214/214 reference-server run at cda3649 (2.033 s). Phase 5b translates the remaining German guides, normalizes headings and clarifies current versus historical status. Phase 5c reviews all 89 Python files for German-language candidates, including runtime, launchers, tests and tools. The detected German text belongs to intentional localized mail, existing aliases or synthetic metadata fixtures; no runtime translation was required. See the [language review](docs/REPOSITORY_LAYOUT.md#phase-5c-source-language-review). Final phase-5 reference-server regression: 214/214 passed at 46799db in 2.041 s. Historical deployment development (superseded by the simplified design described above): Phase 6a completed the reference dependency inventory (Python 3.14.4, Linux x86_64, pip check clean). Phase 6b pins the observed runtime and build-tool versions and adds an isolated local wheel verification procedure; local wheel build, content validation, installed imports/console smoke checks and all 214 source tests passed at 063686e (2.049 s). Phase 6c adds a draft guarded systemd unit, private state and permission contract, and offline syntax checks; 217/217 tests passed at 9d933b5 in 3.767 s, with no ResourceWarnings and successful offline unit syntax verification. Phase 6d.1 introduces tested-in-fixtures release-pointer primitives for atomic code selection and code-only rollback; 225/225 tests passed at c06028a in 2.059 s. Phase 6d.2 adds an unprivileged development staging command, offline installation from a trusted local wheelhouse, a project digest check and eight synthetic staging tests. The package verification script also exercised real versioned installation without activation; 233/233 tests passed at df06366 in 2.046 s, with the final package/staging success message. Phase 6d.3 introduces offline development backup and inert recovery rehearsal with SQLite snapshots, receipt/media checks and a private digest manifest. Initial reference-server run at 0f5386a discovered 245 tests, with five errors in pre-existing staging fixtures and no reported errors in the new backup tests. The corrected staging fixtures passed 20/20 tests under each of umask 002, 022 and 077; 245/245 full tests passed at 1b478fa (3.910 s), no ResourceWarnings. Phase 6e adds a local development-only ZIP with a fixed payload allowlist, commit/digest manifest, verification and isolated staging from the extracted archive. Owner reported 253/253 tests in 2.078 s and the final package, development bundle and versioned staging success message after the 248e49d test instruction (commit not reprinted). Phase 7 begins the [production-readiness review](docs/PRODUCTION_READINESS.md), including an offline structural comparison with the original reference commit. Phase 7a: 257/257 tests passed at 6e468a4 (2.091 s); 147 unchanged normalized definitions, all four reported findings and nine import-inventory differences reviewed. Phase 7b.1 introduces a read-only, synthetic-testable production layout metadata contract for separated administrator/service ownership and disabled activation; nine tests passed in 0.009 s and full 266/266 in 2.094 s at fdc23fe. Phase 7b.2 adds non-root candidate building with copied interpreter, fresh-inode handoff at the original absolute path and a same-owner integration rehearsal. Eleven targeted tests passed in 0.009 s, full 277/277 in 2.103 s and the package/bundle/staging/handoff rehearsal completed at 2f262a8. Phase 7b.3a adds a development-only stop/backup/approval/switch transaction with real synthetic SQLite state and continuous queue/deployment locking; thirteen targeted tests passed in 0.078 s, full 290/290 in 4.431 s at 5282e63 with no ResourceWarnings. Phase 7b.3b.1 adds a fixed-unit administrator-only service control library with digest/loaded-unit checks, activation marker removal, synchronous stop and inactive-state verification; twelve mocked tests passed in 0.007 s, full 302/302 in 2.186 s at 206418f. Phase 7b.3b.2 adds mixed-owner backup into administrator-controlled private storage and a fixed-path update composition; eleven targeted tests passed in 0.054 s, full 313/313 in 4.648 s at cff4b87, no ResourceWarnings. Phase 7b.4a adds a conservative version-1 SQLite schema contract and offline config/credential parser check; fifteen targeted tests passed in 0.055 s, full 328/328 in 2.271 s at 4cfbabe. Phase 7b.4b.1 adds independently approved whole-venv tree digests, candidate readiness and a concrete schema/config/backup gate bound to both release IDs with final pre-switch revalidation. Twelve additional tests (340 expected), reference verification pending. Real systemd and distinct-identity validation remain open. Production recovery and activation remain deferred. Separately, the ongoing L3 reference run at 163f46b reached 977 cycles and 15 new SMTP acceptance entries with no counted failures in the subsequently supplied 2026-11-28 log; all 65 distinct telemetry snapshots reported battery=100; see [L3 evidence](docs/SERVICE.md#l3-interim-results-2026-11-28). See [deployment preparation](deploy/README.md). Local development artifact validation passed; target-platform installation, production artifact authorization and service lifecycle remain pending. From the repository root run `python -m unittest discover -s tests -t . -v`. Existing service and probe CLI commands remain valid in this phase. See [repository layout](docs/REPOSITORY_LAYOUT.md). Do not update a running reference test checkout or deploy this branch as production.

### Deployment simplification (current)

The owner approved the ten decisions recorded in [deploy/README.md](deploy/README.md). The fixed-path root handoff, whole-venv integrity approval, release pointer, privileged update and systemd prototype are removed from the active tree in S1; the final prototype c895064 remains in history and its 340-test suite was not run. Runtime, dependency pins, project wheel/ZIP checks, configuration/schema and full offline backup helpers are retained. Reduced suite: 253/253 passed in 2.141 s at 56979da, with owner-confirmed package/development bundle success. New installer, logging, systemd templates, update and uninstall follow in separate checkpoints. No production deployment, merge, L3 or new camera changes.

Retention requirements (approved, not implemented): configurable 90-day detailed metadata, delivery receipt and automatic SMTP image-age limits, manual older-image delivery, 24-hour post-acceptance image cleanup, 30-day file logs and three update backups. Permanent image archival deferred. Discuss remaining behavioral choices before runtime implementation. See [deployment contract](deploy/README.md#approved-retention-requirements-not-implemented-yet).

Further approved requirements: the automatic 90-day age limit applies to cloud event queries, downloads and SMTP; stop automatic retries for expired events, allow explicit manual camera/date-range delivery, retain configurable 90-day camera telemetry history, and measure receipt retention and 24-hour local image cleanup from confirmed SMTP acceptance. Expired unsent/uncertain deletion, manual resend safeguards and telemetry sampling are not yet decided or implemented.
