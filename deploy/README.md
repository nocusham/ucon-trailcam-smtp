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

Phase 6c result: 217/217 source tests passed at 9d933b5 in 3.767 s with no ResourceWarnings. Offline systemd verification passed; host XFS CPUAccounting warnings were unrelated to this unit. Actual service account, sandbox and lifecycle remain pending.

## 6d.1: release selection and code-only rollback

The versioned release directory will hold a venv built at its final absolute path; do not move a populated venv. A release can be selected only after validation and a matching .ready marker written by the trusted operator. The marker is not a signature or a replacement for artifact verification. deploy/release_layout.py supplies a library function switch_release(root, release) for the future installer. It validates release identifiers and the current pointer, checks the readiness marker and console executable, and replaces current atomically with a relative symlink while holding a pointer lock. Returns the previous release ID (or None on first selection). Selecting an earlier compatible release is code-only rollback; it never restores old state or deletes a release. The root and ancestors must be controlled by the trusted operator; this is not a security boundary for untrusted directories. No production CLI is provided yet. The later wrapper must verify ownership, stop the service, serialize the whole deployment transaction, take a consistent backup and validate state compatibility before selecting a release. Atomic rename does not establish crash durability. Never create the service-enabled marker or start the service automatically.

Test only using temporary synthetic directories: python -m unittest tests.test_release_layout -v. Eight new tests, expected full suite 225. No root privileges, network, systemd or production state needed. Phase 6d.2 implements the installer/update workflow; 6d.3 handles backup and recovery, including the rule that an older database must not be restored as a routine code rollback.

Phase 6d.1 result: all 225 tests passed at c06028a in 2.059 s.

## 6d.2: stage a new version without activation

The development-only command `python -m deploy.prepare_release` prepares a new version in an existing operator-owned root with a releases subdirectory. It requires the local project development wheel, its expected SHA256 digest, and a trusted local wheelhouse containing exact reference dependency wheels and pinned pip. It creates the venv at its final absolute release path, uses offline pip installs, checks versions and dependency consistency, imports the installed runtime, and checks console help before marking the release ready. Existing release directories are never overwritten, and a failure leaves an incomplete directory without a ready marker for inspection. The command refuses root and does not select current, create a service account, install a unit, create service-enabled, start systemd, or read private application state. Do not use it as a production installer. The local wheelhouse is trusted input; the project digest is not a signature and dependencies are not hash-locked.

Run the complete development integration check from the separate worktree with `bash deploy/check-package.sh "$HOME/ucon-trailcam-smtp/.venv/bin/python"`. It now builds a temporary local wheelhouse (including the native KCP wheel), stages an independent versioned release without activation, checks the ready marker and absence of current, and runs the full 233-test source suite using that venv. Package retrieval/build may use the network, but staging installs only from local wheels. The temporary directory is removed on exit. Do not run as root or point it at any production directory. The existing reference venv is unchanged. Production installer orchestration, ownership transfer, stop/backup/compatibility gates and activation are not implemented yet; continue in the next checkpoints.

Phase 6d.2 result: owner reported 233/233 tests at df06366 in 2.046 s and the final `Package and versioned staging checks passed.` message. No production activation. Backup/recovery and production orchestration remain open.

## 6d.3: offline backup and recovery rehearsal (development only)

The backup tool operates on trusted operator-owned development directories containing config.toml and .env, and state/events.sqlite3, its existing .lock file and state/media. Stop all writers before taking a backup; the shared queue flock only excludes cooperating workers. The tool refuses root CLI execution, overlapping source/destination paths, existing destinations, symlinks and nonregular or multiply linked files. No changes to the live database or media are intended. SQLite backup API captures committed WAL contents into a standalone database; do not manually copy a live SQLite file. Copy media and config (including credentials) into a private directory, check SQLite integrity and event/receipt consistency, check retained original hashes and sizes, allow explicitly cleaned sent originals, and write a manifest of all file digests, counts and original media root. Failed output is not an approved backup; inspect/remove it manually before retrying with a new destination. The manifest is not signed and the backup is not encrypted. Keep it outside Git, restrict access, use encrypted storage/off-host copies as appropriate, and do not share raw files or manifest paths.

Development example (only disposable, stopped fixtures; never the active reference checkout):

```sh
python -m deploy.state_backup create --config /path/to/fixture-config --state /path/to/fixture-state --destination /path/to/new-backup
python -m deploy.state_backup verify --backup /path/to/new-backup
python -m deploy.state_backup rehearse --backup /path/to/new-backup --destination /path/to/new-rehearsal
```

Rehearsal verifies and copies media plus events.sqlite3.inert, without copying configuration or credentials. It retains absolute original receipt paths; validation maps paths to the copied media but does not change database contents. Never use the rehearsal as a running queue. A software rollback keeps the newest production state; restoring a historical backup after newer accepted or uncertain SMTP submissions risks duplicate delivery. In actual disaster recovery keep the service disabled, preserve all newer surviving receipts and evidence, verify backup integrity, reconcile affected deliveries with independent inbox/provider evidence, assess schema and path compatibility, and explicitly approve any recovery before activation. No automated restore-to-live command exists. Production account ownership, transaction locking across stop/backup/switch, release compatibility and operational restore procedure still need separate implementation and target validation. Backup has no fsync/power-loss durability guarantee; verify after transferring to durable storage. Tests: python -m unittest tests.test_state_backup -v; full suite expected 245. Do not run these CLI examples against L3.

Phase 6d.3 regression follow-up: first full run failed five existing staging tests because the fixture root was rejected by the ownership/mode guard. The previous package check explicitly set umask 077; the direct suite inherited the shell umask. Fix the synthetic directory creation modes rather than relaxing the guard. Twenty staging/backup tests should pass under umask 002, 022 and 077, then all 245 source tests under the inherited umask with ResourceWarning enabled. No production backup or installation performed.

Phase 6d.3 result: 1b478fa, inherited umask 0002, 20/20 under each of 002/022/077 and 245/245 full regression in 3.910 s; no ResourceWarnings. Development backup and rehearsal validation complete.

## 6e: local development release ZIP

The release builder uses a fixed file allowlist and the project wheel validated against the trusted committed source export. See deploy/RELEASE_README.md for the bundle-specific guide. The ZIP contains only the project wheel, guide, license, changelog, public templates, deployment modules, pinned reference/build requirements, draft unit and manifest. No dependency wheels, SDK code bundled as a dependency, tests, tools, private state or live configuration. The manifest records the claimed source commit and per-file SHA256/size. The verifier requires exactly the allowed paths, no duplicates, regular file attributes and matching digests. It does not authenticate a maliciously regenerated manifest; compare the expected commit and use a trusted artifact source. ZIP bytes are stable for identical inputs with the same compression implementation, not a claim of reproducible project/dependency wheels. The build refuses to overwrite existing output.

Run bash deploy/check-package.sh with the reference interpreter as before. It now archives one explicit commit, builds the project wheel and a temporary development ZIP, verifies the archive against that commit, extracts it and stages from the extracted bundle with a separate local wheelhouse. Then all 253 source tests run. The whole temporary tree is removed at exit; no public artifacts or production install. Production orchestration, license and Debian 13 gates remain open. Verify the complete run before proceeding to phase 7.

Phase 6e result: owner reported 253/253 tests in 2.078 s and the final package/development bundle/versioned staging success message after the 248e49d test instruction. No published artifact or host changes. Phase 7a begins with the read-only committed-source comparison in deploy/audit_runtime.py (development only, excluded from the bundle). See [production readiness](../docs/PRODUCTION_READINESS.md) for outstanding production ownership and orchestration work.
