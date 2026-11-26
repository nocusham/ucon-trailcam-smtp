# UBox protocol research and additional-camera validation plan

Reviewed 2026-11-26. Documentation only, during the DEATTI DL04 soak test. No external program was executed, no new cameras contacted, no third-party code imported, and no changes to runtime, dependencies, configuration or database. The ordered cameras remain untested.

## Scope and evidence

- Reference camera: DEATTI DL04 (Ucon), historically called H4 in this repository. Existing SD-original, SMTP and bounded continuous service tests succeeded.
- Next reference: WOLFANG WT08-WB (Ucon), then Xega XG-23 (UBox), after the agreed first-system milestones. App associations are the project owner's information, not independent hardware verification.
- External source: [mahumadad/ubox-p4p, pinned revision 6f9f87fc31da4eb86531a81b08b3b1ffa4db5fa8](https://github.com/mahumadad/ubox-p4p/tree/6f9f87fc31da4eb86531a81b08b3b1ffa4db5fa8). GitHub metadata reports last push 2026-07-22; later issue reports were also inspected. This was a static source/documentation review, not a reproduction of its experiments.
- Current dependency: [p4p-camera-sdk v0.1.16](https://github.com/ArtemKiyashko/p4p_camera_sdk/tree/v0.1.16). The SDK itself attributes its P4P crypto implementation to ubox-p4p. Its [credentials.py](https://github.com/ArtemKiyashko/p4p_camera_sdk/blob/v0.1.16/src/p4p_camera_sdk/credentials.py) and [p4p_crypto.py](https://github.com/ArtemKiyashko/p4p_camera_sdk/blob/v0.1.16/src/p4p_camera_sdk/p4p_crypto.py) were inspected.

Evidence labels below distinguish our tested behavior, external author reports/source code, and hypotheses to test.

## 1. REST cloud API: high reuse potential

| Aspect | Current Ucon implementation | UBox documented behavior |
| --- | --- | --- |
| Portal | https://portal-uni-acc.ubiam.com | https://portal.ubianet.com |
| App context | app=ucon, ver=2.0.10 | app=ubox, ver=3.0.0 |
| Login | POST /api/v3/login | Same path/method |
| Device list | POST /api/v2/user/device_list | Same path/method |
| Event list | POST /api/user/qry/cloudvideo/list/v2 | Same path/method |
| Password encoding | HMAC-SHA1 with empty key, Base64 translated +/= to -_, | HMAC-SHA1 with 64 zero bytes, same Base64 mapping; equivalent for HMAC-SHA1 |
| Auth header | X-Ubia-Auth-UserToken (case-insensitive header name) | Same header documented |
| Request context | X-UbiaAPI-CallContext with app, version, UUID and language | Same header; documented UBox context additionally includes os=android |
| Device response | data.infos, device_uid, device_name, device_pwd, dynamic_info | Overlapping fields documented |
| Event request | device_uids array, begin/end UTC epoch seconds | Same shape |
| Event response | data.items, uid, itemid, et_utc, img_url, type, battery etc. | uid, itemid, et_utc, img_url documented; other fields need verification |

Source: [ENDPOINTS.md, lines 9–145](https://github.com/mahumadad/ubox-p4p/blob/6f9f87fc31da4eb86531a81b08b3b1ffa4db5fa8/docs/ENDPOINTS.md#L9-L145), compared with this project's cloud_probe.py and pinned SDK credentials.py.

Caveats: ENDPOINTS.md describes a working server.py but that file is absent from the pinned public tree. Its reported REST behavior is therefore documentation evidence, not an inspected executable implementation. Another historical document lists GET/device_list and Bearer authentication; ENDPOINTS.md explicitly prefers POST and X-Ubia-Auth-UserToken based on the author's experience. Verify with normal authorized UBox account requests rather than treating either description as a current API contract. Do not assume cross-login, token interchangeability, regional portal equivalence or continued availability of these app versions. UBox's photo event type, battery value meaning, capture versus event-end timestamp, retention, pagination, entitlement and latest_active_utc are unverified for the XG-23. The UBox notes label online_state=2 as online; do not import that interpretation as proof of physical reachability.

Design proposal after validation: an explicit provider/account abstraction with fixed HTTPS origins, separate credentials (e.g. UBOX_ACCOUNT/UBOX_PASSWORD, proposed names only), independent token/UUID lifecycle and persisted backoff/login incidents. Never send a Ucon token or credentials to a UBox portal or vice versa; do not automatically try multiple portals on authentication failure. Use authorized owner accounts and the exact selected device record. Keep device passwords and account secrets out of logs. Treat the account login as separate from the camera's relay authentication.

## 2. Shared P4P ancestry and practical differences

The external project documents a vendor P4P envelope, master/relay discovery, KCP reliable UDP and an RDT layer. Its video path confirms standard 24-byte KCP segment headers and 32-byte RDT media headers (not a claim that SD file/control frames all use that format). Our current implementation already inherits the UBox crypto/handshake lineage through the pinned SDK and adds DL04-specific corrections.

| Detail | External source | Our validated path / proposed test |
| --- | --- | --- |
| KCP binding | Python kcp >=0.1.6; reference experiments use 0.1.6 | Same installed version on reference server; pin in production packaging |
| Full-block crypto | Rotation, XOR, byte permutation; same algorithm in vendored SDK | Reuse existing implementation; no replacement required |
| Short crypto tails | encode/decode apply XOR only for all remaining bytes | DL04 correction handles power-of-two tails 2/4/8 bytes; test on UBox, not yet assumed universal |
| Outbound relay KCP | wrap_relay_kcp returns plaintext; _relay_one_cycle sends it directly | DL04 relay_compat encodes the complete envelope before sending |
| Relay binding | Compact alive accepted as stream-response alias; conversation echoed | DL04 verifies the echoed requested conversation and uses validated compact response; keep fail-closed checks |
| Receive handling | Direct stream loop calls get_received once per datagram; relay path uses best-effort manual reassembly with gaps | Our receive path drains all queued KCP messages and buffered application frames; gap skipping is unacceptable for originals |
| Output goal | Live HEVC clips/snapshots; short relay bootstrap observed | Complete SD JPEG with metadata size, MD5, SHA256, safe native filename and receipt |

Sources: [p4p_crypto.py](https://github.com/mahumadad/ubox-p4p/blob/6f9f87fc31da4eb86531a81b08b3b1ffa4db5fa8/p4p_crypto.py), especially lines 35–85 and 137–192; [p4p_stream.py](https://github.com/mahumadad/ubox-p4p/blob/6f9f87fc31da4eb86531a81b08b3b1ffa4db5fa8/p4p_stream.py), especially lines 424–454 and 545–584; [KCP_DEMUX.md](https://github.com/mahumadad/ubox-p4p/blob/6f9f87fc31da4eb86531a81b08b3b1ffa4db5fa8/docs/KCP_DEMUX.md#L13-L64). Local comparison: h4_crypto.py, h4_receive.py, probe.py relay_compat and existing development history.

The external author reports about one GOP (roughly two seconds of video) from the relay and repeated KCP windows without progress. The author proposes that upstream ACKs may not reach or be applied by the camera; the findings document also allows missing upstream fields or bounded bootstrap behavior. A phone test using relay-only transport reportedly succeeded. Our DL04 path achieved complete file transfer, but under different camera/network/client conditions. The unencoded outbound wrapper and missing tail permutations are concrete code differences worth testing if a new camera stalls; they are not proven causes of the external failure. Do not assert that relays are universally incapable of sustained transfer, or that our corrections will necessarily solve UBox. Distinguish wake acknowledgement, binding, camera KCP progress, native control reply and actual JPEG completion in diagnostics. Avoid persistent live streams, unnecessary wake bursts and gap-tolerant reconstruction for battery-operated original retrieval. Do not hard-code historical server IPs or open inbound ports simply because an older external example uses a VPS.

See [README sections 4–6](https://github.com/mahumadad/ubox-p4p/blob/6f9f87fc31da4eb86531a81b08b3b1ffa4db5fa8/README.md#L167-L253) and [FINDINGS.md relay analysis](https://github.com/mahumadad/ubox-p4p/blob/6f9f87fc31da4eb86531a81b08b3b1ffa4db5fa8/docs/FINDINGS.md#L304-L337).

## 3. SD-original retrieval is still a separate compatibility gate

External ENDPOINTS.md section 4 describes cloud snapshots but no verified full cloud-video or SD playback implementation. Its IOCTRLS.md lists AVIOCTRL_LISTEVENT among not-yet-wired operations. The public source tree contains no demonstrated equivalent of our verified SD-original file workflow. The open [issue #2](https://github.com/mahumadad/ubox-p4p/issues/2) asks for retrieval of previously recorded footage from a 4G camera SD card. A clip or frame captured from live HEVC is not the original PIR JPEG.

For DL04 we already have staged native SD listing (256/257), timestamp correlation (observed cloud photo type 1 / SD type 4, length 65535), original metadata (260/261), data (262/263), complete block coverage and metadata MD5 checks. These are candidates for a controlled read-only comparison, not a universal UBox command/schema mapping. Never substitute img_url or a live frame silently. If SD list type, metadata checksum, file type or native name differs, stop and investigate against the official app for the owned camera. Do not guess at firmware settings, recording controls or deletion commands. Verify the downloaded file against an independently obtained original from that camera's SD card.

Sources: [ENDPOINTS.md, lines 287–310](https://github.com/mahumadad/ubox-p4p/blob/6f9f87fc31da4eb86531a81b08b3b1ffa4db5fa8/docs/ENDPOINTS.md#L287-L310), [IOCTRLS.md, lines 105–115](https://github.com/mahumadad/ubox-p4p/blob/6f9f87fc31da4eb86531a81b08b3b1ffa4db5fa8/docs/IOCTRLS.md#L105-L115); local h4_events.py, h4_download.py, event_match.py.

## 4. Relevant open upstream issues

Checked 2026-11-26; these are user reports, not confirmed solutions or tests of the ordered XG-23.

- [#2 Recording Retrieval from SD card](https://github.com/mahumadad/ubox-p4p/issues/2), opened 2026-07-18: no solution in the reviewed issue.
- [#3 Accessing 4G camera, password?](https://github.com/mahumadad/ubox-p4p/issues/3), opened 2026-08-26: uncertainty about device credentials. Our preferred approach remains authenticated device-list discovery, not guessed or default passwords. Verify that UBox returns a usable device_pwd for the owner's exact UID.
- [#4 Relay wake acknowledgements but no session on XG-S20-AU4g / RBX](https://github.com/mahumadad/ubox-p4p/issues/4), opened 2026-08-30: another Xega model, XG-S20, firmware 2254.0.19.23, not XG-23. The reporter used a Windows implementation based on the pinned builders, not the unmodified external CLI. Eleven attempts and another reachability probe received wake responses but no binding/session or media; official UBox app live view worked. KCP media delivery was never reached. This is a reason to test pre-session discovery/binding independently and not assume every 4G model is compatible. Our outbound KCP fixes cannot explain a failure that precedes KCP without additional evidence. All three issues were open with no comments when inspected.

## 5. Sleep, hardware and data use

The external research reports an Ingenic T23 platform with Wi-Fi/companion MCU and optional EC618 modem, and distinguishes radio wake from encoder availability. Its local dashboard and some long-stream experiments use on-device SD scripts, LAN tooling and firmware/runtime patches. These are outside our requirements; the exact platforms of the ordered cameras are unknown. A Wi-Fi test result cannot be assumed to hold for an LTE device.

Retain the event-driven approach: passive authenticated cloud polling, no direct session without a due original, short bounded downloads, no continuous live stream, no firmware changes, no on-device scripts. After each model is supported, test after prolonged idle and measure actual SIM usage independently of server UDP estimates. Source: [DEVICE_FIRMWARE.md](https://github.com/mahumadad/ubox-p4p/blob/6f9f87fc31da4eb86531a81b08b3b1ffa4db5fa8/docs/DEVICE_FIRMWARE.md), [APP_INDEPENDENCE.md](https://github.com/mahumadad/ubox-p4p/blob/6f9f87fc31da4eb86531a81b08b3b1ffa4db5fa8/docs/APP_INDEPENDENCE.md).

## 6. Recommended architecture for later multi-provider support

Keep a single application and reuse the verified queue, mail routing, retries, telemetry, retention and later image-footer pipeline. Separate provider/account authentication from camera-specific transport capabilities. Do not duplicate the whole service or switch the dependency during the current soak test. Provider/account identifiers should scope tokens, cloud cursors, login/API incidents and backoff; camera identity must not rely on unproven global UID uniqueness. If a schema migration is needed, preserve existing sent and uncertain receipts, document backup/rollback and test deduplication. Transport variants should be selected explicitly after validation; unsupported cameras fail closed. Never activate newly discovered cameras automatically. No broad concurrent SDK monkeypatching; the current sequential scoped compatibility wrapper must be preserved or replaced by isolated implementation before parallel relay work. These are future design decisions, not implemented configuration options.

## 7. Staged test plan (after the existing first-system milestones)

Use the existing reference Ubuntu development server and separate experimental databases/media directories, private test recipients and authorized accounts. Do not change the active production installation or the current soak-test process. Capture only sanitized metadata and aggregate counters in public notes.

### WOLFANG WT08-WB (Ucon) — first

1. Record actual label, app model, firmware version, app version and whether using a personal SIM; do not publish UID or serial.
2. Enroll in the normal Ucon account, check exact UID and device-list schema, including battery and last-activity field. Keep new camera disabled for automatic service until tested.
3. With app closed, trigger a controlled PIR still and confirm passive cloud detection, event type, timestamp and battery; check that repeated queries alone do not create unwanted recordings.
4. One bounded relay test, then SD listing and original download using the existing DL04 path as a candidate. Compare native name, capture time, JPEG dimensions, MD5 and independent SD original bytes. If incompatible, inspect the ordinary app workflow on the owned device; do not relax validation.
5. Test a batch, idle no-relay behavior, restart deduplication, SMTP routing to a distinct private recipient, and coexistence with DL04. Include a simulated or naturally occurring single-camera failure, ensuring it does not block the other camera. Record actual SIM consumption separately.

### Xega XG-23 (UBox) — second

1. Confirm physical/app model and firmware, then authenticate via a separate ordinary UBox account with an isolated read-only cloud probe. Verify portal/context/response schema using normal app behavior. No automatic trial of Ucon credentials or repeated wrong-password attempts.
2. Discover exact authorized device UID and presence of usable relay credentials, without printing secret values. Test passive event intake with a fresh baseline, repeated PIR stills and app closed. Verify whether cloud entitlement, pagination, timestamps, photo type and battery support the same semantics. Check latest_active_utc independently.
3. Run a bounded P4P diagnostic on the owned camera. Distinguish discovery, wake acknowledgement, session binding, KCP progress and settings/list response. If binding fails, focus on pre-session differences; if KCP stalls, compare wrapper encoding/tails/draining against the existing DL04 implementation and normal app evidence. No blanket retry storms or bypass attempts.
4. Validate SD event/file protocol separately as for WOLFANG. Require full JPEG bytes and verified original identity, not a live clip/thumbnail. If unsupported, leave automatic download disabled.
5. Only after single-camera success, integrate an isolated UBox provider/account into the service. Test Ucon plus UBox concurrently at the application level with sequential relays; independent login/API failure/backoff, per-camera routing, no duplicates, no additional idle wakes and no cross-provider credentials. Run bounded and extended reference-server tests before any deployment upgrade.

## 8. Reuse and licensing

The external repository contains an [MIT LICENSE](https://github.com/mahumadad/ubox-p4p/blob/6f9f87fc31da4eb86531a81b08b3b1ffa4db5fa8/LICENSE) with an interoperability disclaimer; GitHub metadata classifies it as Other/NOASSERTION. The text grants MIT permissions subject to retaining the notices. The current SDK explicitly attributes its vendored codec to that project. If borrowing actual code later, preserve applicable copyright/license notices and verify provenance of each component. This does not resolve the separate SDK-wide licensing question previously recorded. Do not redistribute vendor native binaries or firmware. No additional dependency or external code adopted in this review.

Potential upstream feedback after successful model validation: narrowly scoped tests for encoded relay output, tail handling and complete receive-queue draining, with synthetic fixtures and sanitized aggregate observations. Do not present DL04 results as proof of the cause of issue #4; do not post private captures or identifiers. No external issue or pull request created by this review.

## Conclusion

Highest reuse potential: account-scoped REST event discovery and the shared P4P/KCP foundations. Highest remaining risk: actual relay binding and full SD-original compatibility on the new 4G models. Preserve our verified DL04 implementation; test WOLFANG first, Xega separately, then combine. No change to the current milestone sequence or running soak test.
