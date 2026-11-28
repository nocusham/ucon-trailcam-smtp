# Production-readiness gates (phase 7)

Status: development checks in phases 1–6 passed; phase 7a structural
comparison pending. Not a production release or deployment authorization.

## Evidence and limitations

| Gate | Status | Evidence / remaining work |
| --- | --- | --- |
| Source separation, CLI and English policy | Development pass | Phases 1–5; compare original and relocated runtime in 7a. Preserve German user-facing mail. |
| Automated regression | Development pass | Owner reported 253/253 in 2.078 s after 248e49d test instruction; commit not independently reprinted. |
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
Expected full suite: 257. Record the actual report before closing 7a.

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
