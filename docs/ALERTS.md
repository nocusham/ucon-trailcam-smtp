# Health alerts

**Development status:** the optional alert channel, SQLite incident state, manual SMTP test and service integration are implemented. Live automatic alert delivery and sustained failure recovery remain to be validated. The following sections retain the staged development findings; later sections supersede earlier pending items. No extra periodic camera sessions are required. See [SERVICE.md](SERVICE.md) for the integrated service.

## Configuration

See the annotated [alerts] and [alerts.smtp] sections in [config.example.toml](../config/config.example.toml). For existing installations, copy only those sections; camera settings remain unchanged. The alert channel is disabled when the section is absent or enabled=false. Its private SMTP account has its own server, port, username, password reference and recipient. Prefer an independent provider so an image-SMTP outage does not also disable alerts. Failure reports are plain-text emails without attachments. Only STARTTLS or TLS with certificate verification is accepted; Revierwelt destinations are rejected for alerts. Store the password in .env, for example ALERT_SMTP_PASSWORD. Never include passwords or raw responses in alert text.

| Category | Default | Condition |
| --- | --- | --- |
| Login | 15 min | Repeated failed checks spanning the threshold; a confirmed login code 20005 can trigger an alert without another login attempt |
| API | 30 min | Actual repeated API failures spanning the threshold |
| Original download | 24 h | Repeated unsuccessful SD-original download attempts for known pending cloud events of the same UID spanning the threshold |
| Repeat notice | 24 h | The latest check still indicates the incident persists |
| Alert SMTP retry | 60 min | Previous alert attempt failed |
| Recovery notice | Enabled | Successful check following previously confirmed SMTP acceptance of an alert |

The threshold starts with the first observed failure. Ordinary incidents require at least two failed checks whose time difference reaches the threshold. One unsuccessful check alone does not become a confirmed outage through elapsed time. Code 20005 was observed with an incorrect password; the service must suspend login and allow explicit resumption after credentials are corrected. The initial alert core did not implement this block; the later persistent intake and service do.

Absence of PIR events does not establish reachability. No additional active reachability checks are planned. Camera-related incidents require concrete failed retrieval attempts for known pending cloud events. A missing SD original can cause a download failure without the camera being offline. Local filesystem or SMTP errors are not camera-connection failures. Success for a different event must not silently resolve a still-missing original; recovery only after the affected backlog is resolved. During a global cloud outage, do not infer new camera failures from checks that were not performed. The initial alert core did not implement event-specific attribution, retry scheduling or service recovery conditions; see the later stages below.

## Last camera contact and optional inactivity

On 2026-11-26, the authenticated Ucon device query /api/v2/user/device_list confirmed the field `dynamic_info.latest_active_utc` (integer) on the DEATTI DL04 (labelled H4 in older notes). Other fields: online_state (string), battery and signal (integer), is_battery_charging and is_low_power (boolean). The subsequent live test confirmed a plausible Unix timestamp in seconds (UTC), updated after a new PIR trigger with the app closed and no client-side P4P session. The new activity time was ten seconds after the reported photo event. An earlier activity timestamp fell within a successfully queried window without photo events. This suggests other forms of activity but does not prove regular heartbeats. Status values may be cached; updates without PIR and long-term reliability remain open. Output only selected telemetry fields, never the entire device response containing credentials, SIM identifiers or location information.

`et_utc` remains the photo-event timestamp. The optional inactivity warning for the DEATTI DL04 should primarily use latest_active_utc (seven days without reported activity). For models without this field, seven days without new cloud photo events is the proposed fallback; a temporarily missing or invalid value alone must not switch sources. A warning describes absence of reported activity, not proven offline status. Disabled by default, configurable per camera. No additional active reachability checks. Warn only after successful, sufficiently complete and recent cloud queries; avoid unsupported offline claims when history is unknown, timestamps are invalid or missing, or the API fails. The 24-hour alert for repeatedly unsuccessful original downloads is independent. Inactivity logic was not yet implemented at this research checkpoint.

## Manual test (no camera or cloud access)

```sh
python health_alerts.py --config config.local.toml
# Only if enabled=true and private SMTP credentials are configured:
python health_alerts.py --config config.local.toml --send-test
```

The first invocation validates the alert configuration only. The second sends exactly one explicitly marked test email without changing SQLite state. Never send a test alert to Revierwelt.

## Persistence and integration

health_incidents stores in SQLite the key (category, scope), first/last failure times, count, optional numeric API code, login-block state, recovery time and last alert attempt/confirmed SMTP acceptance. Global scope ucon for login/API; exact UID for camera. The service must call init_health, observe and dispatch_due under its database lock in a single worker. Report only actual checks, never raw data. A healthy check ends an incident; recovery notice requires previously confirmed alert acceptance and an enabled recovery option. The email identifies the local camera alias instead of the UID. State persists across restarts. Successful alerts are rate-limited per incident; after an ambiguous SMTP result, an alert may be retried after retry_minutes. Unlike image mail, this can result in a duplicate alert. Failure of the server itself, internet access or alert SMTP server may prevent delivery; external monitoring would be needed for those cases.

At this development checkpoint, eleven standalone unit tests with temporary SQLite files, synthetic timestamps and simulated SMTP passed. The manual alert test was sent and received successfully on the test server on 2026-11-26. The full expanded suite had not yet been confirmed. Automatic monitoring and changed cloud/SD retry logic were not yet part of that stage.

## Persistent download retries

The explicit SD batch test supports --retry-due (only with a configured camera and --download-queue). Optional [download_retry] specifies initial_minutes (5) and max_minutes (360). The delay after actual failures grows exponentially up to the maximum. SQLite download_retries stores next due time, attempts and confirmed failures per UID and event ID. A cooldown is reserved before relay access; interruption or restart without a confirmed failure does not increment the failure count. Downloaded and sent events remain excluded. An SD-list timeout marks the selected events as failed; missing or ambiguous matches and individual file timeouts also count. Other exceptions, such as local file errors, do not count as confirmed camera failures at this stage. An interrupted batch may defer selected but unprocessed events until the reserved due time.

A camera alert is created only when the same pending original has failed at least twice across the configured alert threshold. Another successfully downloaded image does not clear the backlog. A recovery notice is prepared only after all confirmed failed pending originals are resolved. Manual probes do not send failure emails; the service must evaluate due incidents. No extra camera wake without due originals. At this checkpoint the login block, integrated orchestration, inactivity warning and further failure classification (such as MD5/protocol errors) remained open.

## Persistent cloud intake and login block

cloud_intake.py is an explicitly bounded test without P4P or SMTP. It uses a new SQLite file, stores a startup cutoff and the last successful query end time per enabled UID. No historical events before startup; five-minute overlap and at most one hour of progress per successful query cycle. Events are stored before advancing the cursor so a restart does not lose previously stored events. API failures retain the cursor and create persistent cooldown up to 15 minutes. Global health state persists across restarts. HTTP 401/403 triggers reauthentication. Code 20005 at the login stage only sets a persistent login block in that database without storing password hashes or other secrets. After correcting credentials, run the same test with --resume-login. Resumption is deliberately manual to avoid repeated incorrect logins. Legacy manual diagnostic probes do not use this block. The later continuous service must also apply it to download logins and continue evaluating the independent alert channel during the block. No real incorrect-password test is required; blocking and resumption were tested synthetically. At this stage pagination, long-outage gaps, telemetry/inactivity, multi-camera fault isolation and automatic delivery remained open.

## Passive telemetry and optional inactivity

cloud_intake.py stores a current allowlisted snapshot per enabled UID in camera_telemetry after successful login and every 15 minutes through the same authenticated cloud session: observation time, last valid activity timestamp, battery, signal, online state and charging/low-power flags. No raw response, SIM identifier, coordinates, passwords or tokens. This is a current snapshot, not a time series. No additional P4P connection.

Optional fields directly in [[cameras]] before [cameras.smtp]: inactivity_warning = false and inactivity_days = 7 (1–365). Two fresh observations beyond the activity-age threshold prepare a separate inactivity alert. For models without the field, a monitored sequence of successful cloud photo queries can serve as a conservative fallback; the interval starts at the first current query and resets after an observation gap exceeding one hour. Once an activity field has been observed, missing, invalid, future or backwards timestamps do not switch sources. Missing information proves neither offline status nor recovery. Pagination and photo-query completeness for other models remain unconfirmed. The fallback logic has only been tested synthetically.

When dispatching alerts after a successful current cloud query, the service must explicitly supply fresh_scopes for enabled inactivity profiles to dispatch_due; inactivity notices are suppressed without that parameter. Snapshots older than 30 minutes do not count. The bounded cloud test still sends no email and downloads no images. The two additional configuration fields are optional; existing files remain compatible. Eight new tests (seven telemetry, one refresh integration) and twenty existing alert/intake tests passed locally at this stage; full CLI/SDK integration and photo fallback on actual other cameras were still pending.

## First integrated service

trailcam_service.py evaluates due alerts with --send-alerts and an enabled alert channel even during a cloud login block. Without the flag, preview only; separately authorize original downloads and image delivery. Inactivity delivery is restricted to fresh cloud_activity snapshots following successful cloud queries; the photo fallback remains observational until completeness is verified. See [SERVICE.md](SERVICE.md) for reference-server tests. Automatic alert execution has not been live validated.

SMTP setup failures before message submission now have persistent per-camera retry cooldown and preserve the downloaded original. Ambiguous submissions remain uncertain and require operator review. No separate image-SMTP alarm category yet; the independent alert SMTP retains its own retry logic.
