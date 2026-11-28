# Production-readiness gates (phase 7)

Status: development checks in phases 1–6 and phase 7a passed; phase 7b.1 permission contract verification pending. Not a production release or deployment authorization.

## Evidence and limitations

| Gate | Status | Evidence / remaining work |
| --- | --- | --- |
| Source separation, CLI and English policy | Development pass | Phases 1–5; phase 7a structural comparison reviewed. Preserve German user-facing mail. |
| Automated regression | Development pass | Owner reported 257/257 in 2.091 s at 6e468a4; prior local ZIP integration 253/253. |
| Reference dependencies and packaging | Development pass | Python 3.14.4 Linux x86_64, pinned SDK/KCP, local wheel and ZIP, staging from extracted ZIP. Not target Python 3.13 or hash-locked builds. |
| Unit syntax | Offline pass | Placeholder executable check only. Actual service identity, access and LXC sandbox untested. |
| Backup and rollback | Fixture pass | 245/245 warning-enabled regression and 20/20 under each tested umask. No production backup/restore. |
| L3 reference | Ongoing | Unchanged 163f46b, latest documented 977 cycles; not a candidate live regression. |
| Other cameras | Deferred | Two devices received but not configured or activated. Model/provider compatibility not established. |
| Production installer and updates | Open | Privilege separation, trusted ownership, full stop/backup/switch transaction, schema compatibility and explicit activation. |
| Artifact trust and SDK license | Blocking public release | SDK permission unresolved; no SDK bundling. Digests are not signatures; dependency hashes and native build provenance unverified. |
| Real lifecycle and target platform | Open | Candidate live reference regression, fault recovery, Debian 13 unprivileged LXC, stop/reboot/update and duplicate-delivery checks. |
| Revierwelt | Deferred | Last integration after the preceding gates. |

## 7a: structural comparison

Compare the baseline 163f46ba2e355654a477a62073441dd61bbecb5a with
the explicit candidate commit using deploy/audit_runtime.py. Only read
Git blobs; no runtime imports or live requests. Normalize known module
relocations (including explicit SDK re-exports) in from-import statements.
Map extracted top-level definitions to their new modules, compare ASTs
without line positions, and inventory new/missing/changed definitions,
module-level non-import statements and changes to normalized top-level
import multisets. Review all findings manually; the credential lookup
change was intentional. The audit cannot prove equivalent initialization,
dependency binding, side effects, dynamic imports, class behavior or
network behavior. It does not inspect root compatibility wrappers or
new package initializers; existing architecture and CLI tests cover
their documented contracts. Four synthetic tests exercise normalization,
logic sensitivity, module statements and commit/duplicate guards.
Verification: Owner-reported structural audit at 6e468a4: 33 baseline and 39 candidate modules, 147 unchanged normalized definitions, four findings and nine top-level import inventory differences; full 257/257 tests passed in 2.091 s. Manual source review: local_credentials.read_secret_values and new _default_secret_path implement the intended source-versus-installed .env lookup (remaining parser/security checks unchanged); the identical MIME_SUBTYPE constant moved from smtp_probe to mail_message. The changed import inventories in cloud_probe, probe and smtp_probe and six new modules correspond to the documented helper extraction and SDK re-exports. No unexplained structural findings in the reported scope. The empty UCON_SECRETS_FILE fallback and absence of an implicit installed .env are intentional; live equivalence remains unproven. Expected HTTP fixture warnings and synthetic one-file wheel validation messages are not production errors.

## 7b: production orchestration

The current development staging CLI refuses root and builds private
0700 release directories owned by the invoking operator. The service
runs under a different dedicated identity; simply selecting such a
release cannot establish executable access or root-owned, read-only
code. The backup helper also requires a single operator owner for
config and state; production intends root-owned config.toml and
service-owned .env/state. Design and test safe privilege boundaries
rather than relax these checks indiscriminately.

Implement a serialized deployment transaction around stop, verification
of stopped writers, backup, compatibility review and atomic selection.
Keep persistent state and credentials outside release directories.
Do not automatically create the activation marker or enable/start a
service. Verify first-install behavior with a new empty state; preserve
current accepted and uncertain SMTP receipts across updates and rollbacks.
Do not restore an old DB automatically. Actual disaster recovery needs
an explicit operator procedure and reconciliation with newer receipts.
Assess backup durability/encryption and access controls; keep private
backups out of Git. Test with disposable fixtures before any host changes.

### 7b.1: prepared, disabled layout contract

Use deploy/production_layout.py as a point-in-time read-only library for
checking named filesystem metadata. No production CLI or root operation
is provided. The supplied root must be trusted; UID/GID 0 represent
the administrator and the service identity has nonzero UID/GID.

| Path (relative to filesystem root) | Owner | Mode |
| --- | --- | --- |
| opt/ucon-trailcam-smtp, releases, release, venv, venv/bin | root:root | 0755 directories |
| release .ready | root:root | 0600 or 0644 regular file |
| release venv/bin/ucon-trailcam-smtp | root:root | 0755 regular file |
| current (if present) | root:root | Relative symlink to a checked release |
| etc/ucon-trailcam-smtp | root:service | 0750 |
| config.toml | root:service | 0640 |
| .env | service:service | 0400 or 0600 |
| service-enabled | — | Must be absent during preparation |
| etc/systemd/system/ucon-trailcam-smtp.service | root:root | 0644 |
| var/lib/ucon-trailcam-smtp and media | service:service | 0700 |
| events.sqlite3 and its .lock | service:service | 0600 when initialized; absent for new state |

Named ancestors must be real root-owned 0755 directories, and checked
regular files must have a single link. This deliberately conservative
contract rejects unexpected modes rather than changing them. The marker's
absence is not proof of a stopped service. No recursive permission audit,
ACL/group/mount checks, interpreter symlink resolution, ready-marker
content verification, DB/media validation, systemd verification or
actual service-user execution is performed here. Caller must stop all
writers; point-in-time checks are not race-safe for hostile directories.
A new-state check only checks the named DB/lock absence; media emptiness
and WAL/SHM artifacts need a separate state check. Nine synthetic tests
exercise distinct administrator/service metadata, first install,
initialized state, invalid ownership/modes, unsafe links, marker and
current pointer rejection. Expected full suite: 266.

Subsequent 7b.2 must implement trusted staging/ownership handoff without
moving a populated venv or running untrusted build hooks as root; 7b.3
must implement stop/backup/update/rollback transaction; 7b.4 must verify
state compatibility and controlled activation. Actual target permission
and systemd lifecycle verification remains mandatory in phase 8.

## 7c: licensing and artifact trust

Clarify SDK licensing before public production distribution. No confirmed
project-wide permission; a draft inquiry exists, posting was denied, no
response documented. Do not bundle SDK code or dependency wheels.
Review dependency artifact hashes per supported target, native KCP
build provenance, project artifact identity and release signing/trusted
distribution policy. Development ZIP manifest alone is insufficient.
Do not silently substitute dependency versions or claim a license grant.

## 7d: reference acceptance and target-test handoff

Finish L3 and document owner-confirmed inbox receipt, queue consistency
and independent completeness limits. Only with explicit approval run
the candidate with a distinct test configuration/state; never run a
second delivery worker on the same camera stream simultaneously.
Test controlled event ingestion, original validation, SMTP acceptance
and recipient receipt, no duplicate sends across normal stop/restart,
uncertain outcomes, outages and recovery. Test new models separately;
do not claim support before evidence. Agree on the go/no-go criteria
for the disposable Debian 13 target LXC in phase 8. Actual target
installation, permissions, sandbox, lifecycle and Revierwelt tests
remain mandatory before production. No merge, release publication or
production activation on the basis of development tests alone.
