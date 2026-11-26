# Planned repository layout for LXC transition

Status: design only; current reference-server commands remain unchanged until the restructuring is performed. Complete reference-server retention, SMTP and long-duration tests first.

```text
src/                 installable runtime package
tests/               unit and integration tests, synthetic fixtures only
tools/               manual diagnostic and experimental probes
deploy/              native Debian 13 LXC, systemd and install/update scripts
config/              example configuration and secret-variable templates
docs/                user installation/operations and developer diagnostics
README.md
CHANGELOG.md
pyproject.toml
requirements.txt
```

Extract runtime functions currently imported from probe.py and other diagnostic entrypoints into the runtime package before moving the tools. Keep a single implementation, not duplicate production and test copies. Validate all imports, CLI entrypoints, installed-package tests and upgrade procedures. Pin dependencies (including KCP) and ensure production runs under an unprivileged dedicated user. Build a release package containing only runtime, deployment support, templates and user documentation. Tests and tools stay accessible from the source repository but are not required for installation. Use versioned validated GitHub Releases rather than a floating main checkout; pre-release candidates explicitly marked. Choose final branch/release policy at packaging time.

Separate local secrets/configuration, database, media and service logs from the installed code, for example /etc/ucon-trailcam-smtp and /var/lib/ucon-trailcam-smtp. New production database and media root; do not migrate historical test queues. Never publish real device UIDs, account details, credentials, logs, images or test databases. Preserve private state across upgrades; document backup and rollback. Validate installation, service stop/restart, reboot, upgrade, permissions and no duplicate delivery in the actual unprivileged Debian 13 LXC only after the reference-server tests. Revierwelt live validation remains last. Do not create production LXC yet.
