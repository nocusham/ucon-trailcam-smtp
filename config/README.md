# Configuration templates

These files are public examples, not runtime configuration. From the repository root, create private local files once:

```sh
umask 077
test -e .env || cp config/.env.example .env
test -e config.local.toml || cp config/config.example.toml config.local.toml
chmod 600 .env config.local.toml
```

Edit the private copies only. Replace the placeholder UID, account, SMTP settings and passwords before use. The example alias `testkamera` is retained for compatibility with existing commands; choose any valid local alias. Optional password key names are illustrative and must match the profile's password_env. Alerts and retention are disabled in the example. Never overwrite private files during updates; never source .env as shell code. See [credential handling](../docs/CREDENTIALS.md).

The templates moved from the repository root in phase 5a. Existing private files and CLI arguments remain at their original locations. Installed deployments will use explicit configuration and credential paths; production installation is not yet validated.
