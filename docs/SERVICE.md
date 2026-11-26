# Integrated service: reference-server test

The first sequential integrated service, trailcam_service.py, uses a single queue lock for the complete invocation. It reuses the cloud device response for relay credentials instead of logging in again for each download. A successful cloud cycle permits one bounded SD batch per enabled camera. Selection is based on individual due times, including across midnight, with up to one hour of capture timestamps (+6 seconds on each edge for matching); no full-day scan. A native camera filename is mandatory in the integrated path. Original MD5 and local receipt checks remain in place. No thumbnail substitution.

Each action is independent and explicit:

- No action flags: cloud discovery, telemetry, local image verification and alarm preview only.
- --download: allow a relay for due originals after successful cloud check; no image email.
- --send: send verified downloaded originals using configured per-camera SMTP profiles.
- --send-alerts: dispatch due notices via independent configured alarm SMTP (requires alerts.enabled).
- --cycles N (default 1), or --loop: repeat cycles with interval in seconds (default 60). Ctrl+C to stop; an interrupted SMTP outcome remains uncertain, never automatically resent.
- --resume-login: explicit release after correcting rejected credentials, same database, stop any running worker first.

On login block, deferred cloud check or API error, no new P4P session is opened; previously downloaded originals and alarm dispatch remain eligible. Per-camera download and delivery exceptions are isolated by the outer cycle, but the existing global cloud intake still stops remaining cameras on a cloud error. A missing SMTP password for one camera does not block the others. Existing uncertain delivery blocks the corresponding camera's image SMTP; never manually reset it without checking the recipient. Database failures are fatal when propagated to the outer cycle; legacy SMTP catches some exceptions internally and marks uncertain. No SMTP safe-pre-DATA retry refinement yet.

## Reference server validation

Use the existing persistent intake TEST database with the two pending photos. Verify that all enabled profiles point to the private test recipient, not Revierwelt. Stop other queue workers. Never reuse an older historical diagnostic queue for production.

```sh
python trailcam_service.py --config config.local.toml --queue-db data/events-intake-test.sqlite3 --output-dir media/service-test --cycles 1 --download
```

Expect one relay if due, committed originals and local MIME verification, no SMTP. Repeat the same command; expect no relay if all are downloaded. Then explicitly add --send (private test SMTP only). Repeat to verify zero duplicate mail. --send-alerts will send only due notices; no artificial failure or password-change test is required. For a new production deployment start with a new database and directory, not the test database.

## Remaining limitations

The nine new core tests and 28 existing alarm/intake/telemetry tests passed in the development container. The service entrypoint was syntax-checked. Actual SDK, refactored relay wrapper, native filename requirement, SMTP integration and full suite must be validated on the reference server. SDK and KCP are not installed in the development container. No LXC/Revierwelt validation yet. Photo-event inactivity fallback stays observation-only in service dispatch until cloud completeness is verified. Other camera models, long-gap retention, pagination, protocol/MD5 retry classification, durable SMTP safe pre-DATA retry, repeated incident freshness, multi-camera cloud isolation, bounded retention and systemd deployment remain open. Do not run unattended production before further validation.
