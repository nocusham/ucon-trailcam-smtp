# Planned feature: optional image footer

**Status:** requirements agreed on 2026-11-26; not implemented. Implementation follows the existing milestones (long-duration test, production layout, LXC/systemd, Revierwelt and other open goals). The ongoing field test remains unchanged.

## Goal

Trail-camera images without their own information strip should optionally receive a consistent, legible footer when sent by email. Examples from various camera vendors serve as visual guidance only; no vendor logos, private example images or GPS data are imported into the repository.

Required information for version 1:

| Information | Source |
| --- | --- |
| Camera name | Local configured camera-profile alias |
| Battery level | Battery percentage in the specific photo event metadata |
| Date | Event capture time, et_utc |
| Time | The same capture time, never download or delivery time |

Default: Europe/Berlin with automatic daylight saving changes, DD.MM.YYYY HH:MM:SS; an MEZ/MESZ time-zone label is useful. Display missing or invalid battery data as unknown; never fabricate or silently substitute a later reported battery level. No additional cloud or P4P query solely for the footer.

## Image geometry — mandatory requirement

The footer is **appended below the complete image**. It must not cover, crop, stretch or shrink any part of the photographed scene.

- Preserve original width W and height H for the photo area.
- New canvas: W x (H + F), where F is the footer height.
- Copy the original image at position (0, 0).
- Draw only in the additional area starting at y = H.
- Opaque black background and high-contrast white text. No semitransparent overlay.
- Scale text and spacing with image width, leaving sufficient margins; long valid camera names must not be clipped.
- Default single-line style, for example: `testkamera | Akku: 87% | 26.11.2026 14:58:21`.
- DEATTI DL04 example: 5120 x 2880 pixels plus an illustrative 120-pixel footer gives 5120 x 3000 pixels. The 120 pixels are an example calculation, not an established default height.

The downloaded JPEG remains byte-identical. The delivery copy must be re-encoded as JPEG, so its bytes differ and decoded pixels may vary slightly due to JPEG compression. Do not alter the crop or resolution of the photo area. Test JPEG quality and font selection during implementation.

## Configuration (draft, not supported yet)

Optional per-camera subsection within the existing [[cameras]] profile:

```toml
[cameras.image_footer]
enabled = false
```

This is a planned TOML subsection, not a currently accepted option. Further proposed controls for style, displayed fields, time format, time zone, background/text colors, font size, spacing and height will be defined during implementation. Version 1 should produce a consistent black strip with white information without additional settings. Disabled by default; existing configurations must continue to work unchanged.

## Processing and safety

1. Download the SD original and verify it as before using MD5, JPEG validation and the local SHA256 download receipt.
2. If disabled, attach the unchanged original bytes as before.
3. If enabled, create a separate expanded-canvas delivery copy after original verification and before SMTP. Never overwrite the original; no permanent second image collection is necessary.
4. Validate the delivery copy for JPEG format, full photo area, expected dimensions, allowed size and correct attachment. Keep original-hash verification; validate the modified MIME attachment against the generated copy, not against the original hash.
5. Preserve the original camera filename as attachment name, existing subject and mail metadata. Process each photo with its own event data, including grouped delivery and multiple cameras.
6. On footer-generation failure, do not silently fall back to an unlabelled attachment or deliver incorrect metadata; preserve the original and pending delivery state. Classify the error locally. No camera re-download solely because rendering failed.
7. Preserve duplicate-delivery protection, SMTP retry rules, retention and original receipts. The generated copy and actual metadata used must be auditable in the future implementation.

## Acceptance tests

- Disabled: attachment SHA256 matches the original; existing pipeline unchanged.
- Enabled: original SHA256 identical before and after processing; unchanged width, height increased by footer height; complete photo area without overlay.
- Correct camera name, battery, capture date and time; unknown battery; winter/summer time and clock transitions.
- Small and large resolutions, long aliases, day/night images, appropriate font size and JPEG quality.
- Two camera profiles with different settings; single and grouped delivery.
- Generation and size-validation failures without delivery or another camera access; no duplicate delivery after retry.
- Synthetic images first, then private SMTP tests, then Revierwelt compatibility.

## Out of scope for version 1

GPS, temperature, moon phase, PIR status, signal strength, vendor logos, multiline or vendor-specific layouts. No firmware modification or change to the image on the SD card.
