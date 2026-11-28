# Production-readiness gates (phase 7)

Status: development checks in phases 1–6 and phase 7a passed; phase 7b.1 permission contract verification passed; phase 7b.2 candidate handoff verification passed; phase 7b.3a transaction rehearsal passed; phase 7b.3b.1 service adapter verification pending. Not a production release or deployment authorization.

## Evidence and limitations

| Gate | Status | Evidence / remaining work |
| --- | --- | --- |
| Source separation, CLI and English policy | Development pass | Phases 1–5; phase 7a structural comparison reviewed. Preserve German user-facing mail. |
| Automated regression | Development pass | Owner reported 290/290 in 4.431 s at 5282e63; no ResourceWarnings; prior local ZIP/staging/handoff rehearsal passed. |
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
current pointer rejection. Owner-reported result at fdc23fe: 9/9 in 0.009 s; full 266/266 in 2.094 s. Expected HTTP and synthetic wheel messages.

Subsequent 7b.2 must implement trusted staging/ownership handoff without
moving a populated venv or running untrusted build hooks as root; 7b.3
must implement stop/backup/update/rollback transaction; 7b.4 must verify
state compatibility and controlled activation. Actual target permission
and systemd lifecycle verification remains mandatory in phase 8.

### 7b.2: candidate build and ownership handoff

A dedicated non-root builder (distinct from the service identity) builds
in an empty administrator-assigned final release directory, with local
trusted wheels and the expected project digest. Use venv --copies, not
interpreter symlinks. No readiness marker is created. The builder must
be fully quiescent before an administrator takes over. Establish this
with an isolated account/process boundary in future orchestration;
the handoff library does not enforce process isolation itself.

The administrator, using trusted administrator-controlled code and a
trusted release parent, copies the candidate into fresh inodes in a
private sibling quarantine directory. Do not execute any candidate code
as root. Normalize directories to 0755, regular files to 0644 or 0755
according to source owner execute permission. Reject unexpected owners,
filesystem crossings, writable/special modes, hardlinks, special files,
extended attributes (including ACLs/capabilities), and symlinks other
than the expected venv/lib64 -> lib. Source must contain only venv and
copied executable entrypoints. Retain the old tree in quarantine and
rename the copied tree into the original absolute path; attempt to
restore the old location if the final rename fails. Never select current
or publish .ready. New inodes avoid retained write descriptors to the
original being able to modify the accepted copy. This is not a hostile
filesystem sandbox: trusted ancestors and complete builder quiescence,
no concurrent writers, no unapproved mounts and trusted artifact inputs
are mandatory preconditions. No power-loss guarantee or provenance
authentication. A failure may leave private quarantine output for manual
inspection. Do not blindly delete it as root.

The privileged library has no root CLI, and real privilege orchestration
and service-user smoke checks are not yet implemented. Eleven synthetic
tests plus a real non-root same-owner build/copy rehearsal in
check-package.sh validate the path and content handoff without changing
users or host state. Owner-reported result: 2f262a8, 11/11 targeted in 0.009 s, 277/277 full in 2.103 s, Python 3.14.4 x86_64 and final package/bundle/staging/handoff success. Actual ownership transfer,
trusted input provisioning, isolation, ACL/mount review and acceptance
under the real service identity remain mandatory before activation.

### 7b.3a: same-owner transaction rehearsal

Use deploy/update_transaction.py only with trusted disposable same-owner
paths and trusted caller callbacks. Require an existing ready selected
release, a different ready target, an explicit expected previous release,
a new disjoint backup destination and absent service-enabled marker.
Hold the existing deployment flock before checking current and invoking
quiesce; require explicit True from quiesce and is_quiescent. Then create
a fresh verified backup via locked_backup (the existing create_backup API
still works). Retain the queue flock through read-only compatibility
approval and selection. Verify the backup again, recheck stopped writers
and marker, and compare expected previous within the pointer flock before
atomic replacement. A rollback follows the same sequence with an older
code target and a **new** backup of latest state. Never restore the old
database, delete a backup, or restart the service automatically.

This is a library rehearsal, not a privileged CLI or a production service
adapter. Callback success is an explicit contract, not proof of quiescence
or schema compatibility. The caller must prevent all starts and writers,
including noncooperating processes, and use the same deployment lock.
An absent marker alone does not prove the service stopped. Source state
must be trusted and already initialized; this does not support first
install. Backup verification is integrity, not authenticity or durability.
Failure may leave an incomplete backup or a valid private backup; keep
it for operator review and leave the service disabled. No attempt to
undo a third party's independent pointer modification. The pointer
comparison guards against a stale expected release, not all possible
bypasses of deployment serialization. Thirteen synthetic tests, including real SQLite snapshots, latest receipt preservation, both locks, stop/backup/approval failure and stale pointer rejection, passed in 0.078 s; full 290/290 passed in 4.431 s at 5282e63 with no ResourceWarnings (owner output).

Next 7b.3b must address real service-stop/start inhibition and mixed-owner
backup with distinct root/service identities, without granting the service
write access to administrator configuration or backup storage. 7b.4 must
implement actual schema/config compatibility and controlled first
selection/activation; all require target validation. No production use yet.

### 7b.3b.1: fixed-unit service control

The root-only production_service_control factory uses the fixed
/etc/ucon-trailcam-smtp configuration directory and
/etc/systemd/system/ucon-trailcam-smtp.service fragment. No privileged
CLI or arbitrary unit selection. The trusted administrator supplies the
independently approved SHA256 of the intended unit, not the hash of an
untrusted file. Check named ancestor/fragment/marker metadata, reject
extended attributes on checked directories/files, require the loaded
fragment path, loaded state, no drop-ins, no pending daemon reload,
KillMode=control-group and SendSIGKILL=yes. Fail closed on missing,
duplicate or unexpected show properties. Inhibit starts by removing only
the regular administrator-owned mode-0644 activation marker. Its absence
makes the existing ConditionPathExists guard fail for new starts under
the expected unit; removing it does not stop an existing process.
No mask, enable/disable, daemon reload or marker recreation. Then stop
synchronously using fixed /usr/bin/systemctl with a minimal environment,
a 210-second subprocess timeout and no shell. Check the marker and
reported inactive/dead state, MainPID=ControlPID=0, and Job empty or 0.
On failure leave the marker absent if it has already been removed,
and do not proceed with the update. No automatic restart.

This is a partial adapter, not a complete maintenance lock or proof of
all writers stopped. The caller must hold the deployment lock across
marker removal, stop, backup and selection; integration with the
same-owner rehearsal and mixed-owner backup follows in 7b.3b.2. The
adapter does not prove cgroup emptiness, prevent arbitrary manual
workers or concurrent administrator changes, authenticate the artifact,
or validate all effective unit properties. Actual Debian 13 systemd
show property format (including Job), condition behavior, stop timeout,
cgroup/process checks and service isolation remain target gates. The
twelve tests use synthetic directories and mocked systemctl calls only;
expected full suite 302. No actual service control or production use.

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
