# ucon-trailcam-smtp

Experimental self-hosted SMTP bridge for Ucon 4G trail cameras. No camera firmware modifications or paid cloud storage intended. The UBIA backend is still required for authentication and relay connectivity.

## Status / Projektstand

Target: H4 LTE trail camera, Ucon Android app, currently using a trial SIM, no cloud storage subscription. Field observation (2026-11-25): without a cloud subscription, motion recordings do not generate app notifications in the tested configuration. Recordings become visible only after actively connecting to the camera. Whether the backend nevertheless exposes motion-event metadata is unknown. Field test: Python 3.14.4 imports and account/device discovery work; SDK 0.1.14 and 0.1.16 both receive live video and metadata frames but no recognized SD event response, even with known photos on the SD card. H4 live listing now works without AVCTRL (18/18 records in 8.0 s). Live thumbnail retrieval is confirmed for a network-wake event; activity-photo retrieval and original-photo retrieval are still experimental. SMTP is not implemented yet.

## First test (Linux, Python 3.12+)

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python probe.py
```

Enter your own Ucon credentials locally when prompted. Passwords and device credentials are not printed. The default test logs in and resolves the first registered device without contacting the camera directly. To select another registered device, use `--index 1` (zero-based).

With the camera in a known test state, trigger a recording and close the mobile app before running:

```sh
python probe.py --events --hours 24
```

This makes one relay session and lists SD events. It may wake the camera and consume battery and mobile data. The test may take several minutes and may fail on incompatible models. No unattended polling or settings changes are performed. SDK diagnostics are suppressed to avoid exposing identifiers; never publish raw credentials, device UIDs, tokens, or packet captures without redaction. Test only devices you own or are authorized to access.

## Read-only SD status diagnostics

```sh
python probe.py --sd-status
```

This opens one relay connection, waits for live data, then sends documented SD status (520) and advanced settings read (960) requests, each with up to ten seconds of response polling. It reports frame types, counts, last-frame times and payload sizes, not raw payloads or credentials. No settings are written. A missing explicit response is inconclusive: the camera could use a different response format. The camera may wake and consume data.

## H4 field observations: 2026-11-25

With SDK 0.1.16 and existing photos and a video visible in Ucon's card playback:

| Probe | Total time | First live frame | Last decoded frame | Explicit response |
| --- | --- | --- | --- | --- |
| SD status / settings read | 24.3 s | 4.2 s | 6.8 s | None |
| SD event listing | 94.3 s | 4.2 s | 6.7 s | None |

Only SDK-decoded RDT types 0x10011 and 0x10013 were seen; the latter had 240-byte payloads. No decoded 521, 961, 257 or RDT control 0x10004 response. This does not establish whether requests reached the device or whether additional packets were discarded by the SDK. Longer timeouts alone did not help.

App playback shows network wake events at 17:23 and 17:28 local time, matching Python test times. This is strong evidence that polling may itself create recordings. Physical sleep state and power consumption have not been measured. The app also shows genuine activity events and a video. The SDK maps network wake to event type 3 and activity to type 4; confirm these mappings against actual H4 data before enabling a default SMTP filter. Do not send network-wake recordings by default once classification is validated.

### Next diagnostic: compare official Android app with Python client

Use PCAPdroid (https://emanuele-f.github.io/PCAPdroid/) with the Ucon app filter, PCAP file export and full packet payload enabled. No root or TLS interception is needed for the initial UDP comparison. Stay logged in, use a test recording with non-private content, close the Python client and make one capture of opening card playback, waiting for the list and successfully downloading one known photo. Stop capture promptly. If possible make a separate live-view-only baseline capture. Record the approximate times of actions and whether each succeeded.

A local VPN capture can change network behavior; note any differences in app connectivity. A capture may contain device identifiers, authentication material, IP addresses and private media. Keep it private, never commit it to the public repository, and share only with a trusted analyst after appropriate review. A packet summary alone may be insufficient for application protocol analysis.

## H4 packet capture comparison (2026-11-25)

Offline analysis of two private Android captures (live and SD playback with photo/video): 1,023 and 1,832 outgoing relay KCP datagrams respectively were P4P-encoded. SDK 0.1.16 wraps outgoing KCP without encoding. The probe now applies encoding to outgoing KCP in a scoped patch of the pinned SDK, without editing installed packages. Inbound relay data is already decoded by the SDK.

The SD response is an RDT control frame with marker 4 and native command 257 at offset 12. Its 124-byte body begins at offset 16, with 12-byte event-list header and fourteen eight-byte records (timestamp u32, length u16, type u8, status u8). The upstream decoder strips 32 bytes and loses the first 16 body bytes, causing its RDT parser to reject the remaining 108 bytes. The probe recovers the native response for known control commands and passes the full body to the SDK. Native settings response 961 is also present in the captures. Of the fourteen events, thirteen are type 3 (network wake) and one is type 4 (activity). The sentinel length 65535 is not a duration in seconds for photos. The private captures are not committed.

Observed app order: initial settings request and companion IOCTRL; then AVCTRL, list request 256, companion IOCTRL. This broadly matches SDK 0.1.16. The compatibility changes are experimental and require live H4 validation; no media downloader is enabled yet. Run:

```sh
git pull
python -m pip install -r requirements.txt
python probe.py --events --hours 24
```

## H4 live validation and staged SD request (2026-11-25)

With encoded KCP enabled, `--sd-status` received native settings response 961 (368 bytes). Live video continued until +16.4 s; the earlier stream stopped around +6.8 s. SD status 521 was not decoded. The original SDK event sequence still stopped early (+6.5 s) with no list response, so full SD compatibility is not established.

The Android SD capture shows initial settings + companion at 7.540 s, settings response at 9.319 s, AVCTRL at 9.722 s, event request + companion at 9.753 s and list response at 9.930 s. It also queries local midnight to next midnight (Europe/Berlin, UTC 23:00 to 23:00 on these dates). This suggests testing a staged initialization rather than sending all commands immediately. The app timing does not prove that waiting for settings is required.

```sh
python probe.py --events --day 2026-11-25 --tz Europe/Berlin
```

The default event path now waits for live data, sends the initial pair, waits up to 15 s for 961, continues receiving for 0.4 s, then sends AVCTRL and the list request pair. It polls up to 20 s for list responses and preserves zero-length records. If initialization fails it stops without sending the list request. The previous behavior remains available as `--sdk-events`. The staged mode is experimental and has not been validated with the physical camera. No firmware or persistent settings are modified.

## Staged test K: transport diagnostics

Settings response 961 arrived 1.93 s after the initial request. Last decoded frame at +6.8 s, directly after AVCTRL and SD list requests; no 257 response. App capture confirms exactly the same calendar boundaries and AVCTRL payload as the probe. In the Android capture, KCP PUSH sequence numbers 0–4 were explicitly acknowledged after 117, 117, 207, 177 and 177 ms respectively. App outgoing PUSH segments advertised receive window 512; SDK 0.1.16 configures 256.

The probe now reports outbound PUSH sequence/command, retransmissions, explicit ACK or cumulative UNA, last incoming relay/KCP traffic, and undrained buffer size, without raw packet content. ACK proves transport acknowledgement, not application execution.

Controlled experiments (close the app, one session at a time):

```sh
python probe.py --events --day 2026-11-25 --sd-flow no-av
python probe.py --events --day 2026-11-25 --sd-flow app
python probe.py --events --day 2026-11-25 --sd-flow app --kcp-window 512
```

The first omits only AVCTRL, the second retains the prior sequence, and the third changes only the receive window relative to the second. The alternative paths and telemetry are experimental. A missing application response may still be due to framing or an incomplete session, not necessarily a rejected command.

## H4 successful listing and experimental photo retrieval

Test L (no AVCTRL, window 256) returned all 18/18 records in 8.0 seconds: 17 network wake events and one activity event. Tests M/N (with AVCTRL, window 256/512) both had transport ACKs but no list response. The default is now no-av; app flow remains for comparison. The failed login in the test was an input mistake.

Offline reconstruction of the private SD capture yielded three 640x360 thumbnails and two decodable 5120x2880 JPEGs. The observed file transfer uses native 261 metadata and 263 file frames. One 262 request asks for the whole file, with block count at 1212 and size at 1220. The full 24-byte file body header must be retained. Four of five JPEG checksums did not match the metadata MD5 interpretation, so the probe reports the comparison without claiming integrity verification; it checks contiguous blocks, exact size and JPEG start/end signatures. The higher image size does not prove optical resolution. No raw capture, personal data or image contents are committed.

```sh
python probe.py --events --day 2026-11-25 --download-photo thumbnail
python probe.py --events --day 2026-11-25 --download-photo original
```

These are explicit one-shot experiments: select the newest type-4 event with the observed photo sentinel 65535, use file type 2 or 3, and save in ignored media/ without overwriting. The metadata request uses the selected event record (some Android capture fields varied); exact request behavior and the new native download decoder remain to be validated live. No automatic retries or SMTP. A missing or incomplete file is an error, not success. Do not publish personal images.

## Download tests O/P and compact relay binding

Test O failed before sending commands: 1152 incoming KCP PUSH segments, no outgoing KCP packets or decoded frames. Both original app captures contain a 468-byte relay candidate (0x00421206) and a 36-byte alive reply (0x00421406). Only the alive reply contains the KCP conversation matching subsequent traffic at offset 24. SDK 0.1.16 may accept either reply as binding; the probe now restricts binding to the compact alive response and reports the count of incoming segments matching the chosen conversation, without printing identifiers. This is a plausible explanation for the intermittent startup failure, not verified on a failed Python packet capture.

Test P listed 22/22 events, obtained ACK for 260 and received a 60-byte response 261 with size zero for a type-4 photo. No data request or file write occurred. In the Android capture, some successful metadata requests use the event's actual timestamp/length/flags, others use unexplained values; do not replay those opaque fields. First validate the deterministic thumbnail path for an activity photo and an explicitly chosen known network-wake photo. The second is a diagnostic exception, not a change to the normal activity-only selection.

```sh
python probe.py --events --day 2026-11-25 --download-photo thumbnail
python probe.py --events --day 2026-11-25 --download-photo thumbnail --photo-time 2026-11-25T17:42:16+01:00
```

The known control event had a successful 5246-byte thumbnail in the Android capture (metadata request 260 with actual timestamp, length 65535, source event 3, status 1). The test may differ if the file has since been removed. Metadata diagnostics now report body length and filename length only. Zero-size responses remain errors and do not trigger a data request. A timestamp with an explicit UTC offset is required for manual selection. These changes are not live-validated. If the control succeeds and activity fails, capture a successful in-app download of the exact activity photo next. No paid storage, camera firmware changes or automatic polling added.

## Download tests Q/R: byte-identical live thumbnail

Both tests established a compact alive binding with every observed inbound KCP segment matching the selected conversation. Test Q listed 23/23 events and got positive 261 metadata (6121 bytes) for a type-4 photo; request 262 was acknowledged, but no decoded 263 file frames arrived during 45 seconds of continued live traffic. Test R listed 24/24 records and downloaded the explicitly selected type-3 reference thumbnail (5246 bytes, five blocks) in 9.8 s including login-independent relay setup. Independent offline reconstruction of that file from the prior Android SD capture produced exactly the same SHA-256 digest as reported by the live probe. Thus the tested data-request and block-decoding path produces a byte-identical JPEG for the reference event.

The original Android capture has three thumbnail transfers, all with five blocks; no transfer of the specific type-4 candidate is present. The activity thumbnail needs six blocks. This does not establish whether the event type, block count, request parameters, state or a transient failure caused the missing response. The capture also contains nonzero unexplained trailing fields in some 262 requests; a successful Python reference transfer with zeroed offset and actual size shows that those fields are not universally required. Do not copy opaque values into new requests.

One record in test R had an unfamiliar event type 84 and length 17448. The list count alone does not establish semantic validity of every record. Keep the type-4 filter for automatic selection and compare the unfamiliar record with the app before interpreting it.

Next: capture a successful Android thumbnail/original retrieval of the exact type-4 recording (prefer a short capture limited to Ucon), and if needed one failed Python transfer using tcpdump filtered to UDP port 20001. Compare 260/261/262/263 and the session state. Do not publish packet captures, image content, authentication material or personal identifiers. No further protocol changes until the exact activity-photo transfer is compared.

## Test S: successful Android original-photo capture

A third private app capture shows a complete type-4 original JPEG transfer: metadata size 275548 bytes, type 3, 230 blocks, 5120x2880 pixels. The file was reconstructed and decoded offline with Pillow. The direct original download did not require a thumbnail of the same event beforehand. The app had already downloaded other images in the same session. Its 262 payload is byte-compatible with bulk_request(timestamp, type 3, size 275548), using zero offset. The captured 260 request contains unexplained fields instead of the event timestamp/length/flags; their meaning remains unknown and they are not copied. The previously unusual event type 84 at 18:06:27 local appears as a normal type-3 record in this capture, so it is not established as a distinct event type.

A diagnostic reference mode permits using a known original size if the standard metadata response explicitly reports zero. It still sends the normal metadata request, stops on timeout or a conflicting positive size, and requires explicit event selection and a known SHA256. It saves only a complete JPEG whose SHA256 matches the supplied reference. This tests whether 262 can retrieve the exact file despite the zero metadata response, without guessing opaque 260 fields. It is not the default download behavior, not yet live-validated, and does not solve metadata discovery for arbitrary originals. Exact event timestamps, image hashes and captures are kept out of the public repository.

Example syntax (substitute your own values from a successful local app capture):

```sh
python probe.py --events --day YYYY-MM-DD --download-photo original \\
  --photo-time YYYY-MM-DDTHH:MM:SS+01:00 \\
  --reference-size 275548 --reference-sha256 YOUR_64_DIGIT_SHA256
```

## Test T: correct original metadata, no file frames

The H4 returned the correct 275548-byte original size in native response 261 for the selected activity event. The reference-size fallback was not used. All KCP segments matched the binding, 262 was cumulatively acknowledged, and live data continued throughout the 45-second file timeout, but no decoded 263 file frame arrived. The listing returned 27/27 records. This rules out missing size as a sufficient explanation for this failure.

Rechecking the third Android capture against the current bulk_request layout confirms the successful original 262 payload matches the constructed timestamp, type, count, zero offset, size and zero-filled remaining bytes. Actual Python wire bytes still need verification. Capture UDP ports 20001 and 10240 on the Linux test server (tcpdump with full snap length), repeat the activity original and test a known network-wake original as a control. Compare raw KCP stream reconstruction, native framing, response 261, request 262 and session initialization with the app trace. The app had already retrieved other images and used AVCTRL in its session; the Python path omits AVCTRL for listing because the earlier AVCTRL tests failed. State dependence remains a hypothesis. No additional protocol changes until the server trace is examined. Keep captures private.

## Roadmap

- [x] Verify account login and H4 relay live-data reception.
- [x] Compare Android card-playback traffic with SDK code; identify outgoing encoding and RDT control parsing discrepancies.
- [x] Validate outbound encoding and native settings response recovery on H4.
- [x] Validate staged event retrieval and native event response recovery on H4 (no-AV flow).
- [x] Verify SD event listing.
- [x] Validate live reference thumbnail download byte-for-byte against Android capture.
- [ ] Validate activity-photo thumbnail and original JPEG download on the camera.
- [ ] Test wake from sleep and personal SIM compatibility.
- [ ] Investigate whether the backend exposes motion-event metadata without a cloud subscription; do not assume notifications are available.
- [ ] Measure camera wake duration, battery impact and mobile data use during manual SD queries, including after deep sleep.
- [ ] If no passive event signal is available, evaluate configurable low-frequency polling with backoff, overlapping query windows and no concurrent sessions; leave unattended polling disabled until measured.
- [ ] Optional: Android notification webhook only for configurations where notifications are actually available.
- [ ] Implement SQLite-backed event and delivery queue; deduplicate by camera and event/file identity; exclude verified network-wake events by default.
- [ ] Implement SMTP with TLS certificate verification; retry failures and document possible duplicates after uncertain delivery.
- [ ] Add tests with synthetic fixtures, Docker and setup documentation in German and English.

## References

- https://github.com/ArtemKiyashko/p4p_camera_sdk — existing Ucon cellular relay and SD-card protocol library.
- https://github.com/mahumadad/ubox-p4p — related UBIA protocol research.

Unofficial project; not affiliated with Ucon or UBIA. No vendor code or firmware is bundled.
