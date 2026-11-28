# Ucon trail camera SMTP bridge — local development bundle

**Not a production release.** Do not install as root, activate the included
systemd unit or connect a live camera during the development checks.

This archive contains the project wheel (version 0.0.0.dev0), configuration
templates, selected deployment helpers, a draft unit and project license.
The manifest records the claimed source commit and SHA256/size of each
payload file. The archive contains no third-party wheels, test fixtures,
diagnostic probes, camera data, private credentials or installed environment.
Manifest consistency is not signature verification; obtain the archive from
a trusted source and verify it with the matching repository's
deploy.release_bundle verifier before extracting.

## Local development staging

Use Python 3.14.4 on the reference Linux x86_64 platform for the existing
validated dependency set. Debian 13/Python 3.13 has not been validated.
Supply a trusted local wheelhouse with exact versions listed in
deploy/requirements-reference.txt and the pinned pip from
deploy/requirements-build.txt. Build dependencies and native KCP wheel
reproducibility are not guaranteed. The SDK's redistribution/license status
is unresolved; no SDK or other dependency wheels are included or published.

From the verified extracted bundle, as an unprivileged operator, in a new
private test directory only:

```sh
umask 077
mkdir -m 700 /path/to/new-test-root
mkdir -m 700 /path/to/new-test-root/releases
wheel=dist/ucon_trailcam_smtp-0.0.0.dev0-py3-none-any.whl
# Use the project-wheel digest from the independently verified manifest.
python -m deploy.prepare_release --root /path/to/new-test-root \
  --release dev-check --wheel "$wheel" --sha256 EXPECTED_WHEEL_SHA256 \
  --wheelhouse /path/to/trusted-local-wheelhouse
```

Replace all placeholder paths and the expected digest. Staging only prepares
a versioned environment; it does not select current or start a service.
The bundled unit is a draft, not an authorization to install it.

## Configuration, backup and recovery

Only the example templates are included. Private configuration belongs
outside the bundle: eventually /etc/ucon-trailcam-smtp/config.toml and .env,
with the credential file owned by the service user and mode 0400 or 0600.
Do not source .env as shell code or use it as systemd EnvironmentFile.
Use the explicit UCON_SECRETS_FILE path for installed applications.
Keep the queue and originals in separate persistent private state.
Never point a development installation to the running reference queue.

deploy.state_backup is a non-root, offline development tool for stopped
writers and trusted owner-controlled directories. Its rehearsal is inert;
it does not restore a live database. Backups contain credentials and are
not encrypted by the tool. Keep them private and outside Git. A code rollback
must retain the latest database and media, including all delivery receipts.
Production ownership, activation, schema compatibility and recovery
orchestration are not yet implemented.

See the matching source commit in the
[project repository](https://github.com/nocusham/ucon-trailcam-smtp)
for the full documentation and validation status. The included project
LICENSE does not resolve third-party dependency licensing.
