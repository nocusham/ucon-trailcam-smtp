# Integrated service: reference-server test

Reference camera: **DEATTI DL04**, as confirmed on the camera and retail box. Historical notes and compatibility module names use `H4` for this same reference device; the origin of that label is unverified.

The first sequential integrated service, trailcam_service.py, uses a single queue lock for the complete invocation. It reuses the cloud device response for relay credentials instead of logging in again for each download. A successful cloud cycle permits one bounded SD batch per enabled camera. Selection is based on individual due times, including across midnight, with up to one hour of capture timestamps (+6 seconds on each edge for matching); no full-day scan. A native camera filename is mandatory in the integrated path. Original MD5 and local receipt checks remain in place. No thumbnail substitution.

Each action is independent and explicit:

- No action flags: cloud discovery, telemetry, local image verification and alarm preview only.
- --download: allow a relay for due originals after successful cloud check; no image email.
- --send: send verified downloaded originals using configured per-camera SMTP profiles.
- --send-alerts: dispatch due notices via independent configured alarm SMTP (requires alerts.enabled).
- --cycles N (default 1), or --loop: repeat cycles with interval in seconds (default 60). Ctrl+C to stop; an interrupted SMTP outcome remains uncertain, never automatically resent.
- --resume-login: explicit release after correcting rejected credentials, same database, stop any running worker first.

On login block, deferred cloud check or API error, no new P4P session is opened; previously downloaded originals and alarm dispatch remain eligible. Per-camera download and delivery exceptions are isolated by the outer cycle, but the existing global cloud intake still stops remaining cameras on a cloud error. A missing SMTP password for one camera does not block the others. Existing uncertain delivery blocks the corresponding camera's image SMTP; never manually reset it without checking the recipient. Database failures are fatal when propagated to the outer cycle; legacy SMTP catches some exceptions internally and marks uncertain. Proven failures before send_message (connect/TLS/authentication) now restore downloaded and schedule a persistent per-camera retry. Errors after entering send_message, including explicit refusal, remain uncertain conservatively.

## Reference server validation

Use the existing persistent intake TEST database with the two pending photos. Verify that all enabled profiles point to the private test recipient, not Revierwelt. Stop other queue workers. Never reuse an older historical diagnostic queue for production.

```sh
python trailcam_service.py --config config.local.toml --queue-db data/events-intake-test.sqlite3 --output-dir media/service-test --cycles 1 --download
```

Expect one relay if due, committed originals and local MIME verification, no SMTP. Repeat the same command; expect no relay if all are downloaded. Then explicitly add --send (private test SMTP only). Repeat to verify zero duplicate mail. --send-alerts will send only due notices; no artificial failure or password-change test is required. For a new production deployment start with a new database and directory, not the test database.

## Live validation (2026-11-26)

Full server suite: 154/154 passed. Integrated single-cycle download and SMTP preview succeeded with two 5120 x 2880 originals (261,777 and 259,019 bytes) in one 8.5-second relay session. A second invocation opened no relay, verified both originals and sent two independent STARTTLS messages; both arrived and SQLite recorded two sent events. No alarm was due. The subsequent ten-cycle integrated run completed 10/10 without failure: one new PIR event, one 9.3-second relay, one accepted single-image SMTP message, nine idle cycles without relay, no alarms, and three sent events in SQLite. Previously sent events were not resent.

The next subject-format test uses `camera_smtp.py --preview-sent` against the same test database and day, without --send. This reconstructs the new subject using the configured alias and original capture timestamp (Europe/Berlin, MEZ/MESZ); it does not change or resend earlier messages. For a live check use the private test recipient, trigger a new PIR event and run the integrated service with the three action flags. Longer unattended validation and fault-path testing remain pending.

## Remaining limitations

The nine new core tests and 28 existing alarm/intake/telemetry tests passed in the development container. The service entrypoint was syntax-checked. The normal integrated SDK and SMTP path and full suite are now live-confirmed. Bounded continuous operation, the reference-server soak/restart runs and short transient cloud-failure recovery are live-confirmed within the evidence limits documented below. Sustained outages, actual SMTP/SD failure recovery and automatic alarm delivery for a real incident remain unverified. SDK and KCP are not installed in the development container. No LXC/Revierwelt validation yet. Photo-event inactivity fallback stays observation-only in service dispatch until cloud completeness is verified. Other camera models, long-gap retention, pagination, protocol/MD5 retry classification, repeated incident freshness, multi-camera cloud isolation, bounded retention and systemd deployment remain open. Do not run unattended production before further validation.

## SMTP retry safety

The state is committed as uncertain before transport starts. Only the dedicated SafeSMTPFailure (connection, TLS or authentication failure before invoking send_message) permits a transactional restore to downloaded and deletion of the unaccepted delivery/route receipt. Cooldown is persisted per camera in smtp_retries: 5, 10, 20, 40, then at most 60 minutes. A successful transmission clears it. The service retries at the next due cycle, without re-downloading the original. If the process crashes before restore, uncertain remains and must be reviewed. After send_message starts, even SMTP negative replies are treated as uncertain for now. A confirmed acceptance followed by a QUIT failure is still acceptance. No new alarm category, no config change. The full 167-test server suite passed, including the queue integration tests; live normal SMTP delivery also passed. Actual SMTP fault cases remain simulated. Do not intentionally use a wrong live password to test this; use unittest and private SMTP for the ordinary next photo.

## Local retention

The SMTP-refinement reference test passed 167/167 tests and 4/4 service cycles, with one new original accepted using the requested camera-name subject. No actual failure induced. New optional [retention] enabled=false, days=30 uses confirmed SMTP acceptance time. The standalone media_retention.py requires the same queue and managed media root; defaults to read-only preview. --apply and service --cleanup additionally require enabled=true. Service runs cleanup after first cycle and at most hourly, under queue lock. At most 100 verified originals per invocation; unknown/missing/changed/shared paths or symlinks skipped. Only sent files with acceptance receipt are eligible, and all event/delivery/download rows remain; successful deletion recorded in media_cleanup. Empty managed directories may be removed nonrecursively. No camera deletion, no orphan scan. Crash between unlink and audit commit can leave missing file reported as skipped. Sent-preview cannot rebuild a deleted original. Keep root private to service account; do not share writable directories or modify files while worker runs. The reference server passed 175/175 tests and a read-only preview found zero eligible originals. Actual deletion of old originals was tested with synthetic fixtures only; automatic hourly cleanup remains unverified on the server. Repository separation and installation artifacts deferred to LXC transition, see REPOSITORY_LAYOUT.md.

## 24-hour reference-server soak test (L1)

Use the existing reference test queue and private test SMTP recipients only. Stop other writers, keep cleanup disabled (omit --cleanup), and run the continuous service in a terminal multiplexer such as tmux if available. Set umask 077, keep logs locally in a private ignored data directory, and use unbuffered Python output. Record the initial state counts and start time. No need to induce bad passwords, force the camera awake, or deliberately break networking.

```sh
umask 077
mkdir -p data/logs
set -o pipefail
python -u trailcam_service.py --config config.local.toml --queue-db data/events-intake-test.sqlite3 --output-dir media/service-test --loop --interval 60 --download --send --send-alerts 2>&1 | tee -a "data/logs/soak-$(date +%Y%m%d-%H%M%S).log"
```

Detach the terminal multiplexer without stopping the worker. After approximately 24 hours (optionally extend to 48), stop with Ctrl+C during an idle period, not during SMTP or relay transfer. Read-only SQLite queries may run in another terminal: state counts, cursor timestamps and allowlisted telemetry, acceptance receipt count. Check inbox for one message per new photo, no replay of old photos, idle cycles without relay, timely cursor progress, no unresolved uncertain outcomes or unexpected alarms, and disk usage. A transient error followed by successful recovery is not necessarily a failed soak test. Compare logs and queue status; do not share unredacted configuration, raw captures or private identifiers. After stopping, run one more cycle against the same queue to confirm restart behavior. Do not delete, migrate or reset this queue for production. Successful SMTP acceptance is not proof of inbox delivery; check the recipient. The soak test cannot establish camera battery life or SIM billing. Only after evaluating results proceed with repository packaging and LXC setup.

## L1 interim results (2026-11-27)

Historical interim checkpoint; superseded by the final L1/L2 results below. The owner reported cycle 969 at a nominal 60-second interval (approximately 16.1 hours, not a measured wall-clock duration). Runtime code remains unchanged during the test. The DEATTI DL04 is connected to a USB power supply; the reported 100% battery level is not evidence of low battery consumption.

| Observation | Interim result |
| --- | --- |
| Queue state | 8 sent events total; no pending, downloaded or uncertain rows in the reported state-count query |
| New image deliveries during L1 | 4 SMTP acceptance log entries |
| Camera connections during L1 | 4 relay-opening log entries |
| Last shown original | 5120 x 2880 JPEG, 257,095 bytes, 8.0-second relay; SMTP accepted, correct local capture-time subject |
| Cloud failures | 3 observed, each followed by automatic recovery |
| Persistent cloud retry state | failures=0, next_due=0 |
| Telemetry | battery=100, signal=2, online_state=2; status-code semantics remain unverified |
| Local disk usage | data directory 448 KiB; managed image directory approximately 2.1 MiB (reported du -sh values, cumulative test data) |

The reported queue totals include four previously sent events. Four relay openings and four single-image SMTP acceptances during L1 are consistent with the intended event-driven operation. The provided log excerpts show no additional relay in idle or failed/deferred cloud cycles. These aggregate counts do not independently prove inbox receipt, exact event completeness or a complete absence of duplicates. The reported telemetry snapshot predates the latest shown photo; assess freshness at the end of L1 rather than interpreting the old activity timestamp as a proven camera fault.

### First live transient cloud-failure recovery

Three distinct naturally occurring failure episodes were observed in the supplied log excerpts:

| Episode | Last successful cycle | Failure | Backoff (no request) | Successful retry | Normal polling |
| --- | --- | --- | --- | --- | --- |
| 1 | 98 | 99 | 100 | 101 | 102 |
| 2 | 187 | 188 | 189 | 190 | 191 |
| 3 | 218 | 219 | 220 | 221 | 222 |

Each failure retained retry state and deferred camera downloads. The next cycle performed no cloud request. The subsequent cycle succeeded, with the event-query window expanded from 360 to 480 seconds (300 seconds of overlap plus 180 seconds since the previous successful cursor). Normal 360-second windows resumed on the following cycle. No relay was opened and no alarm was dispatched in the shown failure/backoff/recovery cycles. The observed recovery interval was approximately two minutes at the configured cadence. A subsequent read-only SQLite query showed failures=0 and next_due=0; rendering the latter as a Unix timestamp produces 1970-01-01 and is expected.

This is live evidence of short cloud-failure detection, persistent retry/backoff, catch-up window expansion, successful automatic recovery and retry-state reset. The actual cause (HTTP, API, transport or another error) is unknown because the current logging suppresses details. No new photo was reported in these recovery windows, so retrieval of a photo captured during an outage remains unverified. Longer outages, actual SMTP and SD transfer failures, and automatic alarm delivery for a sustained incident remain open.

### Follow-up after L1

- L1 and L2 are complete (see final results below), including the owner's confirmation of receipt of all six new messages. Retain test queue and logs privately.
- Improve production diagnostics with allowlisted stage/error category, numeric HTTP status and numeric API error code where available; never print tokens, signed URLs, credentials, raw responses or private identifiers. Do not change runtime logging mid-test.
- Separately plan an unplugged battery/SIMbase data-usage trial (suggested at least seven days) under representative PIR activity, with a comparable normal-app baseline. Log photo and relay counts, battery trend and actual provider-reported data volume. The USB-powered L1 test cannot establish battery life or mobile-data savings.

## L1 and L2 final results (2026-11-27)

The owner stopped the reference-server continuous run after cycle 1,529 and ran a separate bounded three-cycle invocation using the same test configuration, database and media directory. The supplied L1 tail contains five successful idle cycles (1,525–1,529). L2 finished with the explicit summary cycles=3, failed=0. No runtime code changes were made during the soak run.

| Observation | Result |
| --- | --- |
| Previously completed unit suite | 175/175 passed on the reference server (not rerun at L2) |
| L1 last completed cycle | 1,529; approximately 25.5 hours at the nominal 60-second cadence, not an independently measured elapsed duration |
| Latest cumulative L1 relay and SMTP counters | 6 relay-opening entries and 6 single-image SMTP acceptance entries |
| Recipient inbox | Owner confirmed all six new L1 messages arrived |
| Latest cumulative L1 cloud failure grep | 3, all previously documented isolated failures at cycles 99, 188, 219; automatic recovery observed in each case |
| Latest L1 queue state | sent=10, no other state rows |
| Latest L1 cloud retry state | failures=0, next_due=0 |
| Latest L1 cumulative disk usage | data 592 KiB, media approximately 2.6 MiB (du -sh) |
| Telemetry | newer snapshot observed, battery=100 on USB power; signal and online-state numeric semantics unverified |
| L2 result | 3/3 successful cycles, failed=0, no relay openings, no SMTP sends, no alarm acceptances or failures |
| Queue after L2 | sent=10, unchanged, no pending/downloaded/uncertain rows |

L2 used the existing queue with --cycles 3 --interval 60 --download --send --send-alerts; cleanup remained off. The first query window was 357 seconds and telemetry was saved; the following windows were 360 seconds. This supports cursor continuity across a normal process restart rather than resetting the intake baseline. All three cycles reported zero new/known/pending events and no due originals or ready deliveries. No old photo was re-downloaded or resent in this idle restart test. The four pre-L1 sent entries and six new acceptances reconcile with ten final sent rows.

Assessment: the reference-server operational soak, recipient delivery and normal idle restart milestones are complete based on the owner's confirmation and supplied counters and excerpts. Cumulative L1 counters were supplied shortly before the final idle tail, not re-collected from an independently audited complete log after shutdown. Do not claim that every L1 cycle succeeded or that every possible camera event was captured. No outage-time photo was observed in the recovery windows. No forced crash, restart with pending or uncertain deliveries, host reboot, sustained outage, real SMTP fault, real SD transfer fault, sustained automatic alarm, actual old-file cleanup, battery endurance or SIM billing validation is established by these runs.

Next engineering stage: improve sanitized diagnostics, then restructure into a single English-language runtime with clearly separated tests, tools, configuration and deployment files. Preserve verified original-download and duplicate-prevention behavior; isolate the SDK boundary so that a later licensed replacement is feasible without copying unlicensed implementation. Resolve SDK-wide licensing before public production distribution; do not bundle the SDK while its terms remain unclear. Keep production deployment and Revierwelt validation deferred until reference-server refactoring and packaging checks are complete. No test state migration to production.

## Sanitized service diagnostics (post-L1/L2)

The service now reports allowlisted error categories and phases rather than raw exception messages. Cloud failures include the stage (login, device_discovery, cloud_event_list), category (for example read_timeout, connect_error, invalid_json, invalid_schema, camera_selection, metadata_rejected, http_status or api_code), validated numeric HTTP/API codes where available, consecutive failures, scheduled delay or manual_resume_required, and the UTC cycle timestamp. A successful cycle after persisted failures reports recovery and clears retry state as before. The timestamp and retry delay are based on the existing cycle time, not an exact network-error timestamp. Example lines below are synthetic, not a diagnosis of the three L1 errors.

```text
Cloud check failed; stage=cloud_event_list category=http_status http_status=503 failures=1 retry_in=120s utc=2026-01-01T00:00:00+00:00; cursor retained.
Cloud retry not due; no cloud requests.
Cloud recovered; previous_failures=1 utc=2026-01-01T00:02:00+00:00; retry state cleared.
SMTP setup failed before submission; stage=auth category=smtp_auth smtp_status=535; state=downloaded; retry in 300s.
SMTP outcome uncertain; stage=submission category=smtp_response smtp_status=451; stopped. Check inbox before manual resolution.
```

SMTP setup diagnostics distinguish TLS context creation, connection, EHLO, STARTTLS and authentication. SMTP reply text is never logged. An exception after entering send_message is still uncertain (including explicit SMTP errors); no automatic resend is enabled. The receipt-commit failure is separate. Alarm SMTP failures, download retry reasons (relay_timeout, missing, ambiguous, download_timeout), generic service exceptions and retention skips also emit bounded diagnostic categories. Download integrity/format errors may still be reported as invalid_value or unexpected; no change to failure classification for scheduling. Unknown exceptions are not printed verbatim. Existing configured camera aliases, subjects, event timestamps and sizes are still logged; keep logs private and redact before sharing. No raw API response, signed URL, account, password, token, recipient address, device UID, filesystem path from exceptions, traceback or exception message is added by these changes. Numeric codes are bounded and arbitrary strings are not interpolated into the new fields. HTTP/SMTP/SDK verbose logging is not enabled.

No schema/configuration change, additional network request, retry timing change, alarm policy change or delivery-state change. The six standalone diagnostic tests passed in the development container with HTTP/SMTP mocks. Four additional cloud integration tests are included; full reference-server suite (expected 185 tests if discovery is unchanged) and normal-service smoke test remain to be run. The three historical L1 failures cannot be retrospectively classified using the old logs.

### D1 retention permission regression

The reference-server D1 run discovered 185 tests, with two retention failures (preview and eligible deletion), while the other 183 passed. The original fixtures reproduce both failures locally under umask 002: pathlib mkdir(parents=True, mode=0o700) applies the requested mode only to the leaf directory; the implicit intermediate key directory is group-writable (0775 under this umask). Retention correctly refuses it. This is a pre-existing fixture assumption exposed by the test environment, not a demonstrated regression of the new diagnostics. The actual reference-server umask has not been measured.

Create the test key and attempt directories explicitly with mode 0700. Also create the real managed media root explicitly before creating the event key directory so a new root does not inherit a group-writable default from implicit parent creation. No existing directory permissions are changed, and all deletion eligibility, owner, mode, path, symlink, digest and receipt checks remain unchanged. New tests cover umask 002 and refusal of a deliberately group-writable directory. The corrected retention and queue-download suites (17 tests) passed locally under each of umask 002, 022 and 077; the original two failures were reproduced before the fix. Full D1 rerun expected 188 tests; D2 still pending. Keep cleanup disabled until validation; no real files were deleted by these tests (only synthetic temporary fixtures).

For future deployment use umask 077 and private service-owned data directories. Existing media directories may still have permissive permissions; inspect them before enabling retention. Do not silently chmod an existing tree or relax the retention checks.

## Deferred image footer

After completion of the existing milestones, an optional per-camera post-download/pre-SMTP transformation will append a dedicated metadata strip below the entire image. It will not overwrite any part of the photograph or change the stored original. With the option disabled, the current exact-original attachment contract remains unchanged. See [IMAGE_FOOTER.md](IMAGE_FOOTER.md). The feature remains deferred; no runtime or configuration changes were made for it during L1/L2.
