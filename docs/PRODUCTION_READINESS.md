# Production-readiness gates

The original fixed-path privileged deployment prototype is superseded by
the owner-approved simplified Linux architecture. See
[deployment contract](../deploy/README.md). Historical implementation
and evidence remain available at
[c895064](https://github.com/nocusham/ucon-trailcam-smtp/tree/c89506433d6aab9b830acf655af2a65190ed335e).
Last verified complete prototype run: 328/328 at 4cfbabe, 2.271 s;
the later 340-test suite was not executed. S1 removes obsolete
prototype-specific tests, not runtime regression coverage.

## Remaining gates

- S1 passed: owner confirmed 56979da, 253/253 in 2.141 s and package/development bundle success.
- Retention/manual delivery: owner approved deleting expired definitely unsent originals, retaining uncertain originals/status until manual resolution, explicit --resend for known successful deliveries, metadata age from capture, telemetry history per fresh observation. R1 implements shared configurable automatic capture-age boundary across cloud event queries, download and SMTP; owner confirmed 259/259 in 2.136 s at 41b3361. No deletions/schema changes yet. R2–R4 cleanup, telemetry and historical manual delivery pending; review next major step before implementation. No permanent image archival in first release.
- S2–S4: implement and validate simple install, logging, optional systemd
  user/system units, backup, update and uninstall, with user-selected
  paths and no root requirement. Preserve private state; no automatic start.
- S5: disposable installation/update/rollback/uninstall acceptance on
  ordinary Linux and Debian 13 (Python 3.13), including paths, permissions,
  dependency installation/native KCP, systemd lifecycle and user lingering.
- Phase 7c: clarify SDK redistribution/license terms (unresolved; inquiry
  draft, no confirmed response). No SDK or third-party wheels bundled.
  Verify application artifact source/digest; do not design a separate
  package manager or require whole-venv hashes.
- Phase 7d: finish L3, check inbox receipt and queue consistency, then
  approved isolated live candidate validation without concurrent workers
  on the same stream. Test other camera models independently.
- Phase 8: actual target LXC validation, Revierwelt delivery last.

Keep main and active L3 at 163f46b; do not modify the running reference
venv, activate new cameras, create production LXC, merge or publish based
on offline tests alone.

SMTP pacing for automated and manual backlog delivery is an additional owner requirement. Review concrete rate and scope before implementation; current per-cycle batch limits alone are insufficient. R1 verification passed at 41b3361, 259/259 in 2.136 s.

Owner-approved SMTP pacing: 30 seconds globally, no daily cap, oldest eligible images first, manual interval override. Restart persistence and alert/scheduling details pending review. Configurable downloads per camera relay are additionally required; actual device limits unknown, existing transfers sequential. Review design and controlled batch tests before implementation.

D1: approved configurable global/per-camera download limit, default 3, range 1–100 experimental, sequential relay; explicit service CLI override. Three new synthetic tests (262 expected), reference and large-batch camera validation pending. D2 pacing approved with SQLite persistence and shared alert priority; not implemented.

D1 owner verified d855099, 18/18 targeted in 0.035 s, full 262/262 in 2.154 s. D2 implements persisted global SMTP attempts, alarm priority and oldest eligible image selection, one image message per service cycle. Seven new tests (269 expected), reference pending. Default 60-second cycle limits actual throughput; no independent dispatch timer, full historical manual command or live SMTP acceptance test yet. Optional pacing table reviewed in schema contract.

D2 verified at 8db4b0d: 55/55 targeted in 0.150 s, 269/269 full in 2.261 s; expected HTTP and synthetic wheel messages. Next R2 design review: cleanup cadence, independent retention interactions and deduplication protection, orphan files and interruption-safe removal, before any runtime change. Live validation remains pending.

R2 owner-approved decisions recorded; R2a accepted-original cleanup with 24-hour default, startup/hourly in send mode, recoverable verified deletion intent and backup consistency check. Five new tests (274 expected), reference pending. R2b expired unsent and metadata/receipt pruning, R2c incomplete attempts after seven days remain pending. No automatic VACUUM or live state changes.

R2a owner confirmed fe9a6d2, 41/41 targeted in 0.102 s, 274/274 full in 2.193 s. R2b.1 adds expired event state, verified expired-original removal, retry/incident retirement and backup validation. Four tests (278 expected), verification pending. No DDL change; older backup validation does not recognize expired state. R2b.2 metadata/receipt pruning, R2c incomplete attempts and R4 historical delivery pending; no live changes.

R2b.1 verified 124d2fb, 47/47 targeted in 0.089 s and 278/278 full in 2.205 s. R2b.2 terminal metadata and receipt pruning implemented with sent_history marker and backup checks; seven tests (285 expected), reference pending. R4 must respect markers and lost history after pruning; older backup validators reject new state. R2c/R3/R4 and deployment/live validation pending.

R2b.2 owner confirmed b6936e8, 47/47 targeted in 0.099 s, 285/285 full in 2.221 s. R2c registered-attempt cleanup implemented, default seven days since creation and last activity; optional download_attempts table reviewed, six tests (291 expected), pending reference verification. Legacy unregistered files retained. No live changes. R3/R4 and deployment/live validation remain pending.

R2c verified 365414a, 44/44 targeted in 0.109 s, 291/291 full in 2.235 s. R3 fresh observation history implemented, independent 90-day configurable pruning and optional schema table, six tests (297 expected), reference pending. No backfill or live change. R4 and deployment/live validation pending.

R3 verified c1f4199, 52/52 targeted in 0.110 s and 297/297 full in 2.264 s. R4 design approval pending; explicit historical range, preview, resend evidence and manual-only processing isolation require review. Live validation remains pending.
