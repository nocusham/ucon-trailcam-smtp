# ucon-trailcam-smtp

Experimental self-hosted SMTP bridge for Ucon 4G trail cameras, using original SD-card images without modifying camera firmware. The UBIA backend is still required for authentication, event discovery and relay connectivity. Paid cloud storage is not intended; service entitlement and long-term availability are not guaranteed.

**Reference camera: DEATTI DL04.** Manufacturer and model designation confirmed by the owner on both the camera and its retail box on 2026-11-26. Earlier development notes use the label `H4`; its origin and status as a vendor or internal hardware designation are unverified. In this repository it refers to the same reference test camera, not a separately validated model. Existing `h4_*` compatibility module names are retained for now.

**Development status (2026-11-26):** the DEATTI DL04 reference camera's cloud discovery, SD original download and SMTP delivery are live-tested, including a bounded ten-cycle integrated service run. Actual failure recovery, longer-duration operation and production deployment still require validation. Do not treat this version as an unattended production release.

## Current status / Aktueller Stand

| Component | Status |
| --- | --- |
| Python / SDK | Python 3.14.4 on Ubuntu test server; SDK 0.1.16 pinned |
| Unit tests | 108 passed on the configured test server |
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
| Continuous service / retry | Pending |
| Proxmox LXC / systemd | Deferred until application validated |
| Revierwelt | Single-image guard implemented; live delivery deferred |

The DEATTI DL04 works with a personal SIM in the reference tests. Cloud event type 1 is a candidate for DL04 PIR stills (SD event type 4, photo length 65535); do not generalize to other models without validation. Remote deletion is not implemented. Actual SIM billing, extended sleep behavior, event availability latency, pagination, entitlement and long outage recovery remain unverified.

## Installation and local configuration

Linux, Python 3.12+ as required by the pinned SDK; use a private checkout and an unprivileged user. For current development stay on the existing Ubuntu test server. Do not create the production LXC yet.

```sh
git clone https://github.com/nocusham/ucon-trailcam-smtp.git
cd ucon-trailcam-smtp
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest -v
umask 077
test -e .env || cp .env.example .env
test -e config.local.toml || cp config.example.toml config.local.toml
chmod 600 .env config.local.toml
nano .env
nano config.local.toml
```

On updates use `git pull` and rerun tests. Do not overwrite existing local configuration. The fully commented German template [config.example.toml](config.example.toml) explains every field. See [credential setup](docs/CREDENTIALS.md) for literal KEY=value syntax, password sources, file ownership and restart behavior. File values override existing environment variables; never source the .env as shell code. Use a separate password entry for each private SMTP credential as needed. Only the public Revierwelt password "mail" is permitted directly in the profile, restricted to the known server and recipient domain. The test suite must never read the real credential file. Earlier credential assertions were fixed in commit 49f6de4; any exposed password should be rotated.

Each camera profile has an independent UID, enabled flag and SMTP host, port, security, sender, recipient, username, password reference, mode and limit. Names are local aliases, not account device indices. Configured-camera image subjects use `UCON testkamera - 15.01.2026 14:52:05 MEZ` (capture date/time in Europe/Berlin with MEZ/MESZ, not server or delivery time). Grouped subjects also include the number of originals and their capture-time range. Original attachment names and bytes are unchanged. Legacy unconfigured SMTP probes retain their original subjects. No fallback to a global destination. Revierwelt requires a distinct recipient for each camera and one attachment per message. Private destinations may use grouped mode, but never mix images from different cameras. One recipient per camera is currently supported. Use STARTTLS or implicit TLS with certificate verification for private mail. Revierwelt's TLS support is not confirmed.

## Current test workflow (manual, not a daemon)

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

## Roadmap / Weitere Entwicklung

- [x] DEATTI DL04 original transfer, cloud event intake, matching, persistent file receipt and SMTP test.
- [x] Per-camera SMTP profiles, protected credentials, UID-based cloud and device discovery.
- [x] Isolate credential tests from local .env; 108 tests confirmed.
- [ ] Integrate UID-based real SD transfer and multi-camera processing on the current server.
- [x] Implement optional independent alarm SMTP configuration and persistent incident notification core (11 local tests).
- [x] Validate manual alert SMTP live (test mail received).
- [ ] Wire observation/dispatch into the service for outstanding original download failures, no extra active camera health checks; validate passive telemetry and wire the optional disabled-by-default inactivity state into automatic dispatch.
- [x] Persistent download retry core with explicit retry-aware SD batch test (core tested locally; live integration pending).
- [x] Persistent intake cursor, startup cutoff, bounded catch-up and login-specific retry block in bounded test (nine core tests).
- [ ] Validate bounded intake live, complete service integration, freshness/pagination validation and automatic alert dispatch.
- [ ] Continuous service with independent cloud, camera and delivery failure handling; configuration for intervals and retention.
- [ ] Device discovery helper; do not auto-enable newly discovered cameras.
- [ ] Test wake after extended idle, event reliability, mobile data use, pagination and service entitlement.
- [ ] Multi-day live test of the DEATTI DL04 on the existing Ubuntu server.
- [ ] Native unprivileged Debian 13 LXC, systemd autostart and actual reboot test.
- [ ] Final Revierwelt delivery test with one original per message.
- [ ] After completion of the existing goals: optional per-camera image footer appended below the complete original image, never overlaid on it; see [planned image footer](docs/IMAGE_FOOTER.md).
- [ ] After first live system: validate WOLFANG WT08-WB (Ucon) and real multi-camera operation.
- [ ] Afterwards investigate Xega XG-23 (UBox), separate account authentication and potential shared protocol/backend; compatibility is unconfirmed.
- [ ] Discuss small upstream SDK fixes with the maintainer after application validation; clarify licensing before redistribution.

## Documentation / Dokumentation

- [German annotated camera configuration](config.example.toml)
- [Credential setup (Deutsch)](docs/CREDENTIALS.md)
- [Optional health alerts (Deutsch)](docs/ALERTS.md)
- [Deferred native Proxmox LXC plan](docs/LXC.md)
- [Planned optional image footer (Deutsch)](docs/IMAGE_FOOTER.md)
- [Full historical development and protocol analysis](docs/DEVELOPMENT_HISTORY.md)
- [Development changelog](CHANGELOG.md)

References: [p4p_camera_sdk](https://github.com/ArtemKiyashko/p4p_camera_sdk) (pinned 0.1.16), [ubox-p4p](https://github.com/mahumadad/ubox-p4p) (related protocol research, not validated as a substitute). Unofficial project; not affiliated with Ucon, UBIA or Revierwelt. No vendor firmware, private captures or personal images bundled.

### SMTP setup retry

A typed SafeSMTPFailure is emitted only for failures before smtplib.send_message is invoked (connection, TLS, authentication). The verified original remains downloaded; the unsubmitted receipt is rolled back atomically with a per-camera cooldown persisted in smtp_retries (5, 10, 20, 40, then 60 minutes maximum). No retry after ambiguous submission; uncertain state still requires manual review. Once SMTP accepts the message, a subsequent QUIT failure does not undo acceptance. Explicit negative replies within send_message are still conservatively treated as uncertain in this implementation. Successful delivery clears the retry cooldown. No new config required; no SMTP-specific alarm category yet. See SERVICE.md. Seven isolated transport/SQLite tests passed locally; two queue integration tests await full server suite.

### Local image retention

Optional [retention] enabled=false, days=30 (1–3650). Age is measured from confirmed SMTP acceptance, not capture time. Preview with media_retention.py --config CONFIG --queue-db DB --output-dir MEDIA (no --apply). Actual removal requires enabled=true plus --apply, or --cleanup on the service (first cycle and hourly thereafter). Only state=sent with accepted receipt and verified hash/size in the managed output directory qualifies; unknown, unsent, uncertain, changed, shared or symlinked files are retained. Event, download and delivery receipts are retained permanently; media_cleanup logs successful file removals. Camera SD cards are not touched. A crash between unlink and audit commit can leave a missing file without a cleanup record, reported as skipped; never reset sent state. Preview of old sent messages may no longer work after removal. 175/175 reference-server tests passed, including synthetic deletion tests; read-only preview found zero eligible originals. Automatic hourly cleanup remains unverified on the server.

Repository packaging and production/test separation are planned for the LXC transition; see [repository layout](docs/REPOSITORY_LAYOUT.md).

The next milestone is a 24-hour reference-server soak test with the existing test database, private SMTP and cleanup disabled. See [SERVICE.md](docs/SERVICE.md#24-hour-reference-server-soak-test-l1) for the procedure. Production packaging and LXC remain deferred.
