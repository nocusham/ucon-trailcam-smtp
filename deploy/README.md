# Deployment preparation

**Development only.** Phases 1–5 passed automated reference-server regression (214/214 at 46799db). The active L3 checkout and virtual environment must remain unchanged. Do not deploy or publish a production release yet.

## Staged plan

| Phase | Scope |
| --- | --- |
| 6a | Read-only inventory of the verified reference Python environment |
| 6b | Exact runtime dependency constraints, build tooling selection, local wheel build and isolated installation checks |
| 6c | Native systemd service and dedicated unprivileged service account, permissions and explicit paths |
| 6d | Installation/update tooling, private state backup and rollback procedures |
| 6e | Versioned release layout and artifact validation |

Production installation and live validation remain later gates. The SDK license is unresolved: do not bundle its code or publish production artifacts until redistribution requirements are clarified. No SDK replacement is planned in this phase.

## Intended filesystem layout

These are proposed deployment locations, not installed paths:

| Location | Purpose |
| --- | --- |
| /opt/ucon-trailcam-smtp/releases/ | Versioned application installations, not writable by the service user |
| /opt/ucon-trailcam-smtp/current | Selected installed version |
| /etc/ucon-trailcam-smtp/ | Private operator configuration and explicit protected credential file |
| /var/lib/ucon-trailcam-smtp/ | Persistent SQLite queue, receipts and original media |
| systemd journal | Sanitized service logs |

Use a dedicated unprivileged service account. Credentials must satisfy the existing owner and mode 400/600 checks. No secrets in the service command line or unit text. Use new production queue and media locations; never copy the reference-test queue into production. Preserve state on updates and fail closed on incompatible upgrades. A code rollback is not automatically a database rollback; later procedures must account for irreversible SMTP acceptance and uncertain receipts.

## 6a: capture the reference baseline

On the reference server, use the Python executable from the already validated virtual environment, without installing or upgrading anything. The following commands query installed metadata only; they do not access cameras, SMTP, databases or configuration files.

```sh
(
set -e
export PYTHONDONTWRITEBYTECODE=1
PY="$HOME/ucon-trailcam-smtp/.venv/bin/python"

"$PY" -c 'import sys, platform; print("Python:", sys.version.split()[0]); print("Platform:", sys.platform, platform.machine())'
"$PY" -m pip --disable-pip-version-check list --format=freeze
"$PY" -m pip --disable-pip-version-check show p4p-camera-sdk httpx httpcore Pillow | grep -E '^(Name|Version|Requires):'
"$PY" -m pip --disable-pip-version-check check
)
```

Review the output before sharing. Record only relevant package names, installed versions, dependency relationships and compatibility findings. Do not publish the full environment inventory indiscriminately, private paths, index configuration, URLs containing credentials or secret values. Do not use an unreviewed pip freeze output as a production lock.

Before phase 6b, requirements.txt and pyproject.toml agreed on direct requirements, but Pillow was a range and transitive requirements were not fully pinned. The exact installed KCP distribution/version and other dependencies must be determined from the working environment. Build tools are separate from the runtime dependency set. Python 3.14 on Ubuntu does not establish Python 3.13 compatibility on Debian 13; validate the target separately. Exact version constraints alone do not establish hash-verified, cross-platform reproducibility.

Next: choose constraints from the verified dependency closure and build a local development wheel in an isolated environment. Do not install the project into the existing reference virtual environment, enable a service or create a production LXC.

## 6a result and 6b package verification

Owner-reported inventory on 2026-11-27: Python 3.14.4, Linux x86_64, SDK 0.1.16, KCP 0.1.6, Pillow 12.3.0; pip check reported no broken requirements. Exact reported versions are recorded in [requirements-reference.txt](requirements-reference.txt) and [requirements-build.txt](requirements-build.txt). The reference list includes observed support packages, including packaging and typing_extensions, without asserting that each is required on all platforms. Source requirements constrain dependency resolution to these versions. Project metadata declares the direct dependencies; deployment must also use the reference constraints. No dependency upgrade is intended.

From the separate test worktree at the phase-6b commit, run:

```sh
bash deploy/check-package.sh "$HOME/ucon-trailcam-smtp/.venv/bin/python"
```

The script requires package-index access (or a configured approved package source), git, tar and an interpreter supporting venv. It installs only into a temporary private virtual environment; if any step fails, it stops and removes the temporary directory. It archives tracked source from HEAD, not working-tree changes or private configuration. It builds only the project wheel locally, checks that no tools/tests/templates/private state/SDK code are inside it, installs it, checks installed imports and --help outside the checkout, and runs the 214 source tests. No service start or live network operation other than package retrieval; no production deployment or published artifact. Report the failing step and sanitized error on failure rather than changing dependency versions. Exact version matching is not hash verification, and the Debian 13/Python 3.13 target still needs its own installation test. SDK redistribution terms remain unresolved.

Phase 6b result: at 063686e the reference environment passed exact version and pip checks, built KCP 0.1.6 from source and the local project wheel, verified 37 runtime Python files, imported 36 installed modules, ran the console command and passed 214 source tests in 2.049 s. A SQLite ResourceWarning was observed; a test fixture connection is explicitly closed in phase 6c. Warning-free rerun pending. The observed wheel hash is recorded in [repository layout](../docs/REPOSITORY_LAYOUT.md); no reproducible-build or target-platform claim.

## 6c: guarded native systemd unit

[Draft unit](systemd/ucon-trailcam-smtp.service) — not installed, enabled or started. The unit runs the installed console entrypoint, not a checkout. The proposed install contract is:

| Path | Owner/group | Mode |
| --- | --- | --- |
| /opt/ucon-trailcam-smtp and releases | root:root | directories 0755; code not service-writable |
| /etc/ucon-trailcam-smtp | root:ucon-trailcam-smtp | 0750 |
| config.toml | root:ucon-trailcam-smtp | 0640 |
| .env | ucon-trailcam-smtp:ucon-trailcam-smtp | 0400 (600 also accepted by parser) |
| service-enabled | root:root | 0644; absent until approved activation |
| /var/lib/ucon-trailcam-smtp | ucon-trailcam-smtp:ucon-trailcam-smtp | 0700 |
| state files and media | service identity | 0600 files, 0700 directories |

The dedicated system account has no login shell and no sudo privileges. The credential file must be service-owned to satisfy the existing parser, while ProtectSystem=strict makes /etc and /opt read-only inside the unit. StateDirectory grants write access to the private persistent state; PrivateTmp supplies isolated temporary storage. No EnvironmentFile interpretation or password in the unit. The installer must not create service-enabled, enable or start the service automatically. The root-owned marker is a further activation guard, not a substitute for operator approval. Removing it prevents subsequent starts but does not stop a running process.

The intended active service polls every 60 seconds with a batch limit of three, downloads originals and sends image emails and configured alerts. It uses a new production SQLite queue and media root. No --cleanup or --resume-login by default. Alerts remain subject to configuration; retention needs a separate explicit opt-in. For staged live validation, first use a separate approved manual invocation without delivery flags. Never point this unit to the active L3 database. Once production activation is approved, the operator explicitly installs the unit, creates the marker, and enables/starts it; those steps are not authorized by this checkpoint.

Restart on failure after 30 seconds, maximum three starts in five minutes. Normal stop sends SIGINT, allows up to 180 seconds, and recognizes exit 130. This is a best-effort shutdown, not a guarantee of atomic SMTP completion: interruption can leave uncertain receipts, which require review rather than blind retries. Do not restore an earlier queue after delivery merely to roll back software. Journal output is unbuffered; sanitized logs still contain local aliases, so restrict log access. The proposed sandbox directives must be validated in the actual LXC.

Offline check from the separate worktree:

```sh
bash deploy/check-systemd.sh
```

This copies the unit to a temporary directory, substitutes only the not-yet-installed executable with /usr/bin/true and runs systemd-analyze verify without starting anything. Static tests check the original command and paths. It does not verify actual account, executable, permissions or runtime sandbox behavior. Do not create users, system directories or install units for this test. The full source regression with ResourceWarning enabled should pass 217 tests without an unclosed connection warning before proceeding.
