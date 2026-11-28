# Deployment architecture

**Current design, not production-ready instructions.** The owner approved
the simplified Linux deployment architecture after phase 7b.4a
(328/328 tests at 4cfbabe). The elaborate fixed-path privileged deployment
prototype through c895064 is superseded; its final 340-test suite was not
run. See Git history for that prototype. Do not alter the active L3
checkout or venv, create the production LXC or publish a release yet.

## Installation contract

Linux; Debian 13 is the reference target, not a container requirement.
Python >=3.12, with Debian's Python 3.13 still to be tested; Python 3.14.4
on the Ubuntu reference server is the validated baseline.

One user-selected installation directory, default ~/ucon-trailcam-smtp
for the chosen runtime account:

```text
ucon-trailcam-smtp/
  .venv/
  config/
    config.toml
    .env
  data/
    events.sqlite3
    events.sqlite3.lock
  media/
  logs/                 # manual/file logging only
  backups/
  install-info.json
```

Use the existing account without root. A dedicated service account is
optional, provisioned separately by an administrator. If installing as
root for another account, expand the default relative to that account's
home and perform application installation/maintenance as that account.
Do not require a root-owned venv or install into /root for another user.
Root is needed only for OS packages, optional account creation and
system-wide unit installation. Do not run the camera worker as root.
The account must have access to the chosen installation path. Ordinary
permissions (private config/state/backups, .env owner and mode 0400/0600)
suffice. Never source .env or use systemd EnvironmentFile; pass the explicit
UCON_SECRETS_FILE path. No hidden application data under /opt, /etc or /var.
Only external systemd unit files and journal are exceptions.

## Operating modes

- Manual: foreground operation, file logs under logs/service.log;
  INFO by default, optional debug, timestamps, rotation at 5 MB with
  five retained rotated files. Keep existing sanitized messages; never
  log credentials.
- systemd user: unit under ~/.config/systemd/user; journal only.
  Availability and lingering depend on the host.
- systemd system: administrator-installed unit under /etc/systemd/system,
  explicitly selected non-root runtime account; journal only.

All modes share one queue and one worker. Never run them concurrently.
The same runtime and explicit absolute config/queue/media paths apply.
No service is started or enabled automatically by installation.

## Approved retention requirements (implementation in progress)

The owner confirmed these configurable defaults on 2026-11-28:

| Data / behavior | Default |
| --- | --- |
| Detailed event metadata | 90 days from capture time, except unresolved state |
| SMTP delivery receipts / duplicate detection | 90 days after confirmed SMTP acceptance |
| Maximum capture age for automatic cloud event queries, image downloads and SMTP | 90 days |
| Camera telemetry history | 90 days |
| Local file logs | 30 days (also 5 MB / five rotated files) |
| Automatic update backups retained | 3 |
| Local image cleanup after successful SMTP acceptance | 24 hours from confirmed SMTP acceptance |

No permanent image archival option in the first release; defer to a
future release. Automatic cloud event discovery, download and SMTP use
the same configurable capture-age limit; stop automatic delivery/retries
for expired events, without disabling the entire service or other cameras.
Manual older-image delivery must explicitly select a camera and date
range, subject to source availability. Exact CLI syntax, preview and
resend safeguards remain to be reviewed; expired delivery receipts mean
prior delivery cannot always be determined. No camera SD-card deletion.
Journal retention remains the administrator's responsibility.

Owner-approved additional decisions: delete definitely unsent local
originals after the automatic capture-age limit; preserve uncertain
originals and their unresolved state until explicit manual resolution.
Known successful deliveries are not resent unless the operator explicitly
requests --resend. Detailed metadata retention starts at capture time;
retain data necessary to resolve unfinished/uncertain state. Historical
telemetry records each fresh successful device observation (normally
about every 15 minutes), without additional requests or fabricated cached
samples. The latest-state table remains for alarms. Manual delivery
cannot guarantee duplicate detection after receipt expiry; exact preview,
confirmation and CLI details require review before implementation.

Implementation checkpoints:
- R1: shared configurable automatic age boundary. Implemented
  [retention].automatic_days (default 90, 1–3650 integer days) in bounded
  cloud event windows, service download selection and service SMTP selection.
  Inclusive capture cutoff; fresh queue still starts at current time.
  Stale cursor catch-up skips expired backlog, retains the one-hour window
  and commits the cursor only after successful store. No deletion or
  schema change; older downloaded/uncertain state remains for now.
  Explicit existing diagnostic date-range commands retain their old
  behavior; the new manual historical delivery/resend workflow is pending.
  Six additional tests; owner confirmed 259/259 in 2.136 s at 41b3361.
- R2: safe media cleanup after 24 hours from SMTP acceptance, expired
  definitely unsent originals, metadata and receipt pruning with
  unresolved-state protection, retry/health consistency and backup
  compatibility. Review deletion/ordering and independent configurable
  periods before implementing.
- R3: 90-day fresh-observation telemetry history and pruning.
- R4: explicit manual camera/date-range delivery and --resend safeguards.

The legacy enabled/days media-cleanup configuration is unchanged in R1
and remains disabled by default. The approved 24-hour default takes
effect only in R2. No deletion in R1, no automatic migration, no permanent
image archive. The existing uncertainty block remains in effect.
Document decisions before each major implementation; preserve L3.
Update backup rotation must not silently delete manually created backups;
review implementation before S4.

## Simplification implementation checkpoints

| Checkpoint | Scope |
| --- | --- |
| S1 | Remove superseded privileged deployment prototype and fixed units; retain application wheel, dependency pins, local development ZIP, structural audit, configuration/schema and offline backup checks. |
| S2 | Simple install.sh and manual instructions; user-selected directory, conventional venv/pip, project artifact verification, pip check, private templates, install-info. No user management or root Python. |
| S3 | Manual logging with rotation and user/system systemd templates using selected absolute paths; no automatic start. |
| S4 | Backup and update.sh, optional media, code rollback retaining latest state, uninstall.sh preserving data by default. |
| S5 | Local disposable install/update/uninstall and target acceptance, documentation and release gates. |

For updates stop all writers, verify backup, install reviewed application
artifact, run pip check and offline config/schema checks, restart only
on explicit request. Preserve config, queue, receipts and media; never
rewind a database to roll back code. Optional media omission must be
clearly recorded and must not be represented as a complete recovery
backup. Restore procedures must account for absolute media paths and
irreversible SMTP acceptance. The retained state_backup.py is still the
existing same-owner full-media offline backup/rehearsal; its interface
will be adapted in S4. No automatic migration or general-purpose
transaction/security framework.

## Development validation

```sh
python -m unittest discover -s tests -t . -v
bash deploy/check-package.sh /path/to/reference/python
```

The package check exports committed source, builds an isolated venv,
checks exact reference dependency versions and wheel contents, builds and
verifies the development ZIP, installs the extracted project wheel,
checks pip/imports/CLI outside the checkout and runs the regression suite.
No live service, root access, or actual production data. No third-party
wheels are bundled; SDK licensing and native KCP/target dependency
validation remain open. S1 passed: owner confirmed commit 56979da, 253 tests in 2.141 s and final package/development bundle success. Complete R1–R4 before final installer configuration; review the next major step with the owner before implementing.

See ../docs/PRODUCTION_READINESS.md and ../docs/LXC.md for release gates.

## SMTP throughput (D2 verified offline)

The owner requires paced image delivery during backlog processing; no bulk burst of e.g. 90 individual messages. Current per-camera image batch limits and service cycle interval are not a persistent email-rate limit. Owner approved a configurable 30-second minimum interval globally across image SMTP messages, no additional daily cap, oldest eligible ready images first, and the same manual delivery rate by default with an explicit per-invocation override. Provider limits may require lower rates. The owner confirmed persistence of the last SMTP attempt across restart in SQLite, and alert priority with the same global minimum interval. D2 implements the initial service-cycle-based scheduler and shared persisted attempt accounting; historical manual workflow remains pending.

## Camera download batch configuration (D1)

Owner approved a global default of 3, optional per-camera override, integer
range 1–100 (experimental software cap), sequential originals in one relay.
The selected service limit is CLI --batch-limit when explicitly supplied,
otherwise [cameras.download].batch_limit, otherwise [download].batch_limit,
otherwise 3. Existing SMTP limit is independent. The bounded one-hour SD
selection window, due ordering, per-original commits and timeout behavior
remain unchanged. The cap is a maximum, not a promise to retrieve that many
images per relay. No parallel transfers or protocol changes.

D1 implements parsing, service selection and CLI range. Owner confirmed
18/18 targeted tests in 0.035 s, 262/262 full in 2.154 s at d855099.
Actual batches above 3 remain unvalidated on camera hardware; later isolated
5/10/20/50/100 tests require owner approval and must not interrupt L3.
The standalone diagnostic probe's existing limits are unchanged.
SMTP pacing D2: [smtp_pacing].interval_seconds defaults to 30, integer
1–3600, one shared persisted attempt timestamp per queue SQLite database.
Reserve before SMTP or delivery-state transition; failed attempts count,
throttling defers without changing event/incident attempt state. Clock
rollback postpones attempts until elapsed wall time permits. Alarm dispatch
precedes image dispatch, using the same gate; outstanding due alarms
take priority. Image dispatch considers all enabled cameras, oldest
eligible capture first (grouped message ordered by its oldest image);
respect existing camera cooldown and uncertain-delivery blocks.
At most one image message per service cycle. No sleep for SMTP cooldown,
no parallel workers, no daily cap. With the default 60-second cycle,
actual throughput is normally at most 60 single-image messages/hour,
not the theoretical 120/hour. Independent dispatch cadence is not
implemented; long sequential downloads can delay mail.

Existing explicit camera_smtp and queue_smtp diagnostics use the gate
with --smtp-interval override (camera config default or 30 for queue
diagnostic). These bounded invocations can defer remaining messages and
exit; they are not the future full historical delivery command. Direct
standalone SMTP/alert test probes without queue state are diagnostics,
outside the service gate; do not run them concurrently with the service.
Manual R4 workflow must reuse the same queue and gate. New optional
smtp_pacing table is included in reviewed backup schema; no existing
table migration. D2 owner confirmed 55/55 targeted tests in 0.150 s and
269/269 full regression in 2.261 s at 8db4b0d. Expected HTTP and synthetic
wheel messages. No actual SMTP or camera operations in these tests.

## R2 design review (pending owner approval)

Approved retention durations remain unchanged. Discuss cleanup cadence,
protection of minimal deduplication records until automatic eligibility
ends even if independently configured receipt retention is shorter,
handling of untracked partial/orphan files, and crash-safe file deletion
before implementing R2. Never delete uncertain originals or remote SD
files. Coordinate local file/receipt pruning under the existing queue
lock; retain evidence for failed deletions. Existing cleanup unlinks
before committing its receipt, so interruption reconciliation needs a
focused regression test. Do not introduce general-purpose privileged
or transactional deployment frameworks. Proposed rules are not approved
or implemented. R2 must preserve backup validation and manual resend
semantics; review before code changes.
