# ucon-trailcam-smtp

Experimental self-hosted SMTP bridge for Ucon 4G trail cameras. No camera firmware modifications or paid cloud storage intended. The UBIA backend is still required for authentication and relay connectivity.

## Status / Projektstand

Target: H4 LTE trail camera, Ucon Android app, currently using a trial SIM, no cloud storage subscription. Field observation (2026-11-25): without a cloud subscription, motion recordings do not generate app notifications in the tested configuration. Recordings become visible only after actively connecting to the camera. Whether the backend nevertheless exposes motion-event metadata is unknown. Field test: Python 3.14.4 imports and account/device discovery work; SDK 0.1.14 and 0.1.16 both receive live video and metadata frames but no recognized SD event response, even with known photos on the SD card. Photo download compatibility remains unverified. This initial prototype only tests login and optionally lists camera events. It does not download images or send email yet.

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

## Roadmap

- [x] Verify account login and H4 relay live-data reception.
- [x] Compare Android card-playback traffic with SDK code; identify outgoing encoding and RDT control parsing discrepancies.
- [x] Validate outbound encoding and native settings response recovery on H4.
- [ ] Validate staged event retrieval and native event response recovery on H4.
- [ ] Verify SD event listing, thumbnails and original JPEG download.
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
