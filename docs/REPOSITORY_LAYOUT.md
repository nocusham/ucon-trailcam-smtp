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

## English-only repository policy

As part of the repository restructuring, English is the single project language throughout the maintained source tree and GitHub presentation. Translate existing German and mixed-language material, preserving technical meaning, and apply the same policy to new contributions.

- All README files, documentation, installation and operating guides, configuration examples and comments, changelog and release notes use English.
- Source code identifiers, comments, docstrings, command-line help, diagnostic messages, service logs, error messages, test names and test descriptions use English.
- Deployment scripts, systemd unit descriptions, packaging metadata, GitHub templates, new commit messages, issue and pull-request templates use English.
- Translate historical development documentation where necessary without changing recorded findings, dates, measurements or original quoted evidence. Do not rewrite existing Git history.
- Keep configuration keys, database schema, external protocol fields and CLI compatibility stable unless a separately documented migration is required. Do not translate user-defined camera aliases or vendor names.
- Distinguish repository language from user-facing localization: preserve the agreed image email subject, German capture-time formatting (MEZ/MESZ), and existing user-facing mail content during the restructuring. Localized output may be made explicitly configurable later; do not silently change its behavior as part of a documentation or naming cleanup.

Before a production release, review the entire maintained tree for remaining German or mixed-language project text, run the complete test suite, verify installed CLI help and deployment instructions, and record intentional localization exceptions. This is a required restructuring acceptance criterion, not a change to the currently running soak-test version.

## Future provider and transport boundaries

The UBox source review suggests separating account/provider-specific REST authentication and polling from model-specific P4P/SD compatibility, while sharing the existing verified-original queue, SMTP, alert and retention logic. During restructuring preserve the validated DEATTI DL04 path and keep UBox disabled/unimplemented until tested. Do not infer compatibility from a brand name or common app alone. Later support multiple independent provider/account sessions, credential namespaces, persistent cursors and login/API incidents; migrate database identity safely if UID uniqueness across providers/accounts is not established. See [UBOX_RESEARCH.md](UBOX_RESEARCH.md). These are architecture considerations, not a request to add UBox runtime behavior before the first validated release.
