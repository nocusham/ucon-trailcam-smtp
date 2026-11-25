# ucon-trailcam-smtp

Experimental self-hosted SMTP bridge for Ucon 4G trail cameras. No camera firmware modifications or paid cloud storage intended. The UBIA backend is still required for authentication and relay connectivity.

## Status / Projektstand

Target: H4 LTE trail camera, Ucon Android app, currently using a trial SIM, no cloud storage subscription. Field observation (2026-11-25): without a cloud subscription, motion recordings do not generate app notifications in the tested configuration. Recordings become visible only after actively connecting to the camera. Whether the backend nevertheless exposes motion-event metadata is unknown. Compatibility with the SDK is unverified. This initial prototype only tests login and optionally lists camera events. It does not download images or send email yet.

## First test (Linux, Python 3.12+)

```sh
python3.12 -m venv .venv
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

## Roadmap

- [ ] Verify account login and H4 relay compatibility.
- [ ] Verify SD event listing, thumbnails and original JPEG download.
- [ ] Test wake from sleep and personal SIM compatibility.
- [ ] Investigate whether the backend exposes motion-event metadata without a cloud subscription; do not assume notifications are available.
- [ ] Measure camera wake duration, battery impact and mobile data use during manual SD queries, including after deep sleep.
- [ ] If no passive event signal is available, evaluate configurable low-frequency polling with backoff, overlapping query windows and no concurrent sessions; leave unattended polling disabled until measured.
- [ ] Optional: Android notification webhook only for configurations where notifications are actually available.
- [ ] Implement SQLite-backed event and delivery queue; deduplicate by camera and event/file identity.
- [ ] Implement SMTP with TLS certificate verification; retry failures and document possible duplicates after uncertain delivery.
- [ ] Add tests with synthetic fixtures, Docker and setup documentation in German and English.

## References

- https://github.com/ArtemKiyashko/p4p_camera_sdk — existing Ucon cellular relay and SD-card protocol library.
- https://github.com/mahumadad/ubox-p4p — related UBIA protocol research.

Unofficial project; not affiliated with Ucon or UBIA. No vendor code or firmware is bundled.
