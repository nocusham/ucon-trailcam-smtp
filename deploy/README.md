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
validation remain open. S1 verification pending.

See ../docs/PRODUCTION_READINESS.md and ../docs/LXC.md for release gates.
