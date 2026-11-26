# Integrated service: reference-server test

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

The nine new core tests and 28 existing alarm/intake/telemetry tests passed in the development container. The service entrypoint was syntax-checked. The normal integrated SDK and SMTP path and full suite are now live-confirmed. Continuous operation, actual failure cases and automatic alarm delivery for a real incident remain unverified. SDK and KCP are not installed in the development container. No LXC/Revierwelt validation yet. Photo-event inactivity fallback stays observation-only in service dispatch until cloud completeness is verified. Other camera models, long-gap retention, pagination, protocol/MD5 retry classification, repeated incident freshness, multi-camera cloud isolation, bounded retention and systemd deployment remain open. Do not run unattended production before further validation.

## SMTP retry safety

The state is committed as uncertain before transport starts. Only the dedicated SafeSMTPFailure (connection, TLS or authentication failure before invoking send_message) permits a transactional restore to downloaded and deletion of the unaccepted delivery/route receipt. Cooldown is persisted per camera in smtp_retries: 5, 10, 20, 40, then at most 60 minutes. A successful transmission clears it. The service retries at the next due cycle, without re-downloading the original. If the process crashes before restore, uncertain remains and must be reviewed. After send_message starts, even SMTP negative replies are treated as uncertain for now. A confirmed acceptance followed by a QUIT failure is still acceptance. No new alarm category, no config change. Seven isolated local tests passed; two queue integration tests pending server validation. Do not intentionally use a wrong live password to test this; use unittest and private SMTP for the ordinary next photo.

## Local retention

The SMTP-refinement reference test passed 167/167 tests and 4/4 service cycles, with one new original accepted using the requested camera-name subject. No actual failure induced. New optional [retention] enabled=false, days=30 uses confirmed SMTP acceptance time. The standalone media_retention.py requires the same queue and managed media root; defaults to read-only preview. --apply and service --cleanup additionally require enabled=true. Service runs cleanup after first cycle and at most hourly, under queue lock. At most 100 verified originals per invocation; unknown/missing/changed/shared paths or symlinks skipped. Only sent files with acceptance receipt are eligible, and all event/delivery/download rows remain; successful deletion recorded in media_cleanup. Empty managed directories may be removed nonrecursively. No camera deletion, no orphan scan. Crash between unlink and audit commit can leave missing file reported as skipped. Sent-preview cannot rebuild a deleted original. Keep root private to service account; do not share writable directories or modify files while worker runs. Eight local tests passed; full suite and CLI integration pending. Use preview against the reference test database before enabling deletion. Repository separation and installation artifacts deferred to LXC transition, see REPOSITORY_LAYOUT.md.
