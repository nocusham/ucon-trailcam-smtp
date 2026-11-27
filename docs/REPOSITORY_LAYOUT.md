# Planned repository layout for LXC transition

Status: phase 3a implemented; reference-server validation pending on `refactor/repository-layout`, based on the validated `163f46b` runtime. The reference-server cold-weather run (L3) must remain on its current checkout. Do not merge or switch that checkout during L3. Reference-server retention preview, normal SMTP, nominal 24-hour soak (1,529 cycles), recipient receipt of all six new messages and normal process restart (3/3 cycles) are complete within the evidence limits in [SERVICE.md](SERVICE.md#l1-and-l2-final-results-2026-11-27). Improve sanitized diagnostics before restructuring; preserve verified behavior and repeat the full test suite.

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

## SDK boundary and licensing gate

Keep the pinned SDK behind a narrow, testable transport/authentication interface rather than spreading its imports throughout the service. Preserve the working DL04 path and existing failure/receipt guarantees. A replacement is a contingency, not a current implementation requirement. Distinguish independently developed code and MIT-licensed ubox-p4p components from SDK-specific code without a confirmed project-wide license. Clarify permissions before public production distribution; do not bundle the SDK while terms remain unresolved. Avoid copying unlicensed implementations into a replacement. A license clarification request draft exists; posting through the connected GitHub integration was denied, and no maintainer response is known. Do not treat the existing NOTICE as a repository-wide MIT grant.

## Phase 1: test separation and SMTP extraction

Move all existing test modules into the `tests` package, retaining their test cases. Use `python -m unittest discover -s tests -t . -v` from the repository root. Extract image loading, MIME construction and the send wrapper into `mail_message.py`; the service and alerts no longer import the SMTP diagnostic CLI. Keep the legacy probe entrypoint and helper exports, message content, attachment bytes, send boundary, credentials path, database and CLI flags unchanged. The runtime is still at the root until cloud and P4P extraction are complete. Next: extract cloud REST functions, isolate the SDK relay adapter from `probe.py`, then move the runtime under `src/` and manual entrypoints under `tools/`. Move templates and translate maintained documentation as part of those subsequent phases. Do not build production artifacts or bundle the SDK at this point. The full relocated test suite and live regression checks are required before merge.

Phase 1 verification: all 30 test modules are present in `tests/`, no root test modules remain, and 28 relocated modules are byte-identical. The other two adjust imports/mock targets only. The 29 locally available tests (retention, queue download, safe diagnostics and SMTP message/transport) pass with both explicit package discovery and default root discovery under umask 002. Tested file hashes match the branch blobs. The other 159 baseline tests and live integration remain pending on the configured reference server; no camera connection or SMTP delivery was attempted in the local tests. Existing documentation command examples referring to individual root test modules are historical until their migration in later phases; prefix them with `tests.` for package-mode execution.

## Phase 2: cloud REST extraction

Extract the existing ApiError class and six REST/account-selection helpers from cloud_probe.py into cloud_api.py, preserving their implementations verbatim. trailcam_service.py and cloud_intake.py now import this runtime module directly; probe.py uses its exact-UID credential helper. The original cloud diagnostic CLI still re-exports the helpers and retains its existing schema inspection, image download, event export, watch and queue options. There is only one REST implementation and one ApiError class. No REST request shape, host, app context, token handling, password encoding, camera selection, retry policy, cursor, telemetry, configuration or database change. The SDK credential dependency is still required; isolating the remaining SDK relay dependency is phase 3. No new provider or UBox support is introduced.

Six new tests cover login/discovery/refresh/event-query request shapes and session reuse, login rejection, missing token, malformed event arrays, fail-closed exact UID selection and selected-record relay credentials. All six passed locally with HTTP mocks and an isolated synthetic SDK credential interface (real SDK not installed). The test runner's synthetic SDK was not committed or distributed; normal test discovery on the reference server uses the pinned installed SDK. The extracted implementations are byte-identical to their original class/function block, and tested module hashes match GitHub blobs. The expected full suite is 194 tests; full SDK-backed verification and live regression remain pending. No real cloud request, camera wake or SMTP operation was performed. Continue L3 on the existing 163f46b checkout; do not merge during the running test.

## Phase 3a: shared SDK relay adapter

Move the existing DiagnosticRelay class and relay_compat context manager from probe.py into sdk_relay.py. The service imports the shared adapter directly and the diagnostic CLI re-exports both names. The class and context manager bodies are unchanged; the probe main function is unchanged. Preserve sequential relay ownership, scoped SDK monkey patches, stdout/stderr suppression, traffic accounting, binding checks, frame recovery, download logic and failure semantics. Keep the SDK pinned at 0.1.16. No new provider, protocol change, dependency replacement, configuration or database migration.

Static checks confirm the unchanged extracted block and probe main function and the service import change. Three new tests cover the shared adapter identity and restoration of all nine SDK patch targets and both output streams after normal exit and a synthetic TimeoutError. They do not open a relay or send mail. The development environment lacks the real SDK; these tests and the expected full 197-test suite (188 baseline + 6 phase 2 + 3 phase 3a) must be run with the existing reference-server virtual environment from a separate clean worktree. Do not switch the active L3 checkout or copy private state. Phase 3b (remaining SDK boundary review) follows verification; live regression and merge remain deferred.

Reference-server verification (2026-11-27): the owner reported `Ran 3 tests in 0.041s` and `OK` after the targeted adapter test step for commit `3c8693b`. Only the unittest summary was supplied, not the commit or SDK version output. The next step is one full test-discovery run in the separate worktree with the existing virtual environment, covering phases 1, 2 and 3a together (expected 197 tests). No live operations or production merge authorized.
