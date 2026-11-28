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
- Retention/manual delivery: owner approved deleting expired definitely unsent originals, retaining uncertain originals/status until manual resolution, explicit --resend for known successful deliveries, metadata age from capture, telemetry history per fresh observation. R1 implements shared configurable automatic capture-age boundary across cloud event queries, download and SMTP; six additional tests (259 expected) pending. No deletions/schema changes yet. R2–R4 cleanup, telemetry and historical manual delivery pending; review next major step before implementation. No permanent image archival in first release.
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
