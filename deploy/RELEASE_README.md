# Ucon trail camera SMTP bridge — local development bundle

**Development only; not a production release.** This bundle contains the
project wheel, public config templates, offline backup/config/schema helpers,
reference dependency versions and project license. No SDK or other dependency
wheels, credentials, media or live state are distributed. Verify the matching
bundle manifest using the trusted source checkout before extraction. The
manifest checks integrity, not provenance or signatures.

For a disposable unprivileged local test, with trusted dependencies available:

```sh
umask 077
python3 -m venv /path/to/new-test/.venv
/path/to/new-test/.venv/bin/python -m pip install -r deploy/requirements-reference.txt
/path/to/new-test/.venv/bin/python -m pip install --no-deps dist/ucon_trailcam_smtp-0.0.0.dev0-py3-none-any.whl
/path/to/new-test/.venv/bin/python -m pip check
/path/to/new-test/.venv/bin/ucon-trailcam-smtp --help
```

Replace the test path with a fresh directory. Do not start the service or
reuse live credentials or state. Reference Python 3.14.4 Linux x86_64 has
been tested; Debian 13/Python 3.13 target verification remains open.
The SDK license remains unresolved. This bundle is not an installer;
the simplified install/update/uninstall scripts and systemd templates
are planned separately. See the matching repository's deploy/README.md.
