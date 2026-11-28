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

## SMTP throughput requirement (design review pending)

The owner requires paced image delivery during backlog processing; no bulk burst of e.g. 90 individual messages. Current per-camera image batch limits and service cycle interval are not a persistent email-rate limit. Owner approved a configurable 30-second minimum interval globally across image SMTP messages, no additional daily cap, oldest eligible ready images first, and the same manual delivery rate by default with an explicit per-invocation override. Provider limits may require lower rates. Persisting the attempt timestamp across restarts is recommended but not explicitly confirmed; review alert handling and nonblocking scheduling before implementation. No rate limiter implemented yet.

## Camera download batch requirement (design review pending)

The owner requires configurable downloads per camera connection; the camera's actual limit is unknown. Current service --batch-limit defaults to 3 (allowed 1–10), shared across cameras; queue_download.download_batch transfers selected originals sequentially in one relay, not concurrently. Preserve the validated sequential protocol until parallel transfer support is established. Proposed global default with optional per-camera override and explicit manual diagnostic override, initially retain the tested conservative batch and bounded SD listing window. Review scope, limits and a controlled batch-size experiment before implementation. No assumption that 10 is a camera hardware limit, and no live change to L3.
