# Local credentials and restart behavior

The installation uses two local, untracked files: config.local.toml (camera and SMTP settings) and .env (confidential credentials). Both persist on disk. In a Git checkout, the default .env remains in the repository root after the phase 4b move to src/. An installed package has no implicit .env search path; set UCON_SECRETS_FILE to the absolute path of the protected file or use process environment variables. No shell sourcing, additional dependency or interactive password manager is required.

```sh
umask 077
test -e .env || cp config/.env.example .env
test -e config.local.toml || cp config/config.example.toml config.local.toml
chmod 600 .env config.local.toml
nano .env
```

The credential file must be owned by the process user and have mode 600 or 400. Symlinks, nonregular files, duplicate keys and malformed entries are rejected. Use UTF-8, NAME=value, one key per line; no export or quote syntax. Everything after the first equals sign is literal, including special characters and spaces. Comments occupy separate lines. Do not execute the file with source. File values take precedence over exported variables; missing keys fall back to the process environment. A missing implicit default file is allowed; a missing explicitly selected UCON_SECRETS_FILE is an error. Never log file contents or passwords.

```dotenv
UCON_ACCOUNT=account@example.invalid
UCON_PASSWORD=YOUR_UCON_PASSWORD
SMTP_PASSWORD=YOUR_SMTP_PASSWORD
SMTP_PASSWORD_KAMERA2=ANOTHER_SMTP_PASSWORD
```

In config.local.toml, password_env references a key, not a password. The only permitted literal password is the public Revierwelt credential, password = "mail", restricted to smtp.revierwelt.de and an @revierwelt.de recipient. Omit password_env in that case. A username without a password source, or two simultaneous sources, is rejected. For SMTP without authentication, omit username and both password fields. Revierwelt live testing remains deferred until project completion.

Manual Ucon probes use read_credentials() and may prompt for missing values. The unattended service uses read_credentials(interactive=False) and must stop with a clear, secret-free error if credentials are missing. camera_smtp.py loads credentials only for actual delivery. The legacy SMTP probes also read their global SMTP_* settings through the local loader; these are separate from the multi-camera configuration.

For the future systemd service, the dedicated unprivileged account will read the protected file directly. Set UCON_SECRETS_FILE=/absolute/path/.env in the unit if needed (path only, no secrets). A restart should need neither an interactive login nor export commands if the service is enabled and the file exists and is readable. The unit and actual system reboot test remain pending. Do not use the file as a systemd EnvironmentFile: its quoting semantics differ.

File permissions do not protect against root, a compromised service, disk theft or unprotected backups. Treat backups of configuration, databases and credentials as confidential. A private password file is not encrypted. SMTP without TLS also transmits private content unencrypted; the public password does not change that.

## Confirmed test results (2026-11-26)

Login from the local .env succeeded after the exported variables were removed. Both local files had mode 600. Since commit 49f6de4, the Ucon login tests have been isolated from actual installation credentials; assertion failures do not print credentials. The full 108-test suite subsequently passed on the configured test server. Deliberately incorrect credentials produced login API code 20005. Automatic retry suspension for this code was still pending at that checkpoint; the later persistent intake and service implement the login block and explicit resume procedure described in [SERVICE.md](SERVICE.md) and [ALERTS.md](ALERTS.md). Rotate accidentally exposed passwords and update .env; do not include secrets in reports.
