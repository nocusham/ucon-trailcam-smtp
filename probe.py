"""One-shot, read-only Ucon compatibility probe for your own camera."""
import argparse
import asyncio
import sqlite3
import tomllib
from download_retry import parse_retry, init_retry, due_ids, reserve, record_failure, sync_download_health
from health_alerts import load_alerts
import contextlib
import datetime as dt
from ucon_auth import read_credentials
from camera_selection import profile_uid
from cloud_api import get_device_by_uid
import io
import logging
from collections import Counter
from importlib.metadata import version
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from h4_events import list_events_staged
from event_match import queued_times, match_events
from queue_download import batch_lock, load_rows, eligible, check_existing, download_batch
from cloud_image import validate_image
from h4_download import download_photo, MAX_SIZE
from sdk_relay import DiagnosticRelay, relay_compat
from pathlib import Path
import time

from p4p_camera_sdk.credentials import CredentialClient
from p4p_camera_sdk.sdcard_client import SdCardClient
from p4p_camera_sdk.sdcard import (
    IOTYPE_GET_SD_STATUS_REQ, IOTYPE_GET_SD_STATUS_RSP, build_get_sd_status,
    IOTYPE_GET_ADVANCE_SETTINGS_REQ, IOTYPE_GET_ADVANCE_SETTINGS_RSP,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', type=int, default=None, help='Legacy diagnostic camera index')
    parser.add_argument('--config', type=Path, help='Local camera profile configuration')
    parser.add_argument('--camera', help='Enabled configured camera name')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--events', action='store_true', help='Explicitly request SD events (may wake camera)')
    modes.add_argument('--sdk-events', action='store_true', help='Legacy SDK event sequence (known bad command constants; diagnostic only)')
    modes.add_argument('--sd-status', action='store_true', help='Test read-only SD status and settings requests')
    window = parser.add_mutually_exclusive_group()
    window.add_argument('--hours', type=int, default=24)
    window.add_argument('--day', type=dt.date.fromisoformat, help='Calendar day YYYY-MM-DD')
    parser.add_argument('--sd-flow', choices=('app', 'no-av', 'stop-after-list'), default='no-av',
                        help='Default no-AV or experimental AVCTRL before/after listing')
    parser.add_argument('--no-live-wait', action='store_true',
                        help='Experimental: send settings immediately after relay binding')
    parser.add_argument('--no-audio', action='store_true',
                        help='Experimental: AVCTRL with_audio=0 (requires --sd-flow app)')
    parser.add_argument('--traffic-stats', action='store_true',
                        help='Traffic statistics are now always printed for relay sessions')
    parser.add_argument('--output-dir', type=Path, default=Path('media'),
                        help='Local JPEG directory; existing files are never overwritten')
    parser.add_argument('--download-photo', choices=('thumbnail', 'original'),
                        help='Download one latest activity photo after a successful event list')
    parser.add_argument('--download-queue', type=Path,
                        help='Explicit original batch test; no SMTP')
    parser.add_argument('--batch-limit', type=int, default=3)
    parser.add_argument('--retry-due', action='store_true', help='Explicit retry-aware batch; records failures but sends no mail')
    parser.add_argument('--match-queue', type=Path,
                        help='Read-only match of queued cloud events to H4 SD photos; no download')
    parser.add_argument('--native-filename', action='store_true',
                        help='Use safe camera-reported filename for original photos')
    parser.add_argument('--photo-time', type=dt.datetime.fromisoformat,
                        help='Explicit photo event time, including UTC offset; permits a network-wake control test')
    parser.add_argument('--reference-size', type=int,
                        help='Diagnostic only: known original size from a successful app capture')
    parser.add_argument('--reference-sha256',
                        help='Required SHA256 of the exact reference original')
    parser.add_argument('--kcp-window', choices=(256, 512), type=int, default=256,
                        help='KCP receive window; default SDK 256, Android observed 512')
    parser.add_argument('--tz', default='Europe/Berlin', help='Time zone for --day (default Europe/Berlin)')
    args = parser.parse_args()
    if bool(args.config) != bool(args.camera) or (args.config and args.index is not None):
        parser.error('Use --config and --camera together, without --index')
    args.camera_uid = None
    if args.config:
        from camera_smtp import load_profiles
        try:
            args.camera_uid = profile_uid(load_profiles(args.config), args.camera)
        except Exception:
            parser.error('Invalid configuration or camera missing/disabled')
    args.index = 0 if args.index is None else args.index
    if args.index < 0 or not 1 <= args.hours <= 168:
        parser.error('index must be nonnegative; hours must be 1–168')
    if not 1 <= args.batch_limit <= 10:
        parser.error('--batch-limit must be 1–10')
    if args.download_queue is not None and (not args.events or args.day is None
            or args.sd_flow != 'app' or args.match_queue is not None or args.download_photo
            or args.no_live_wait or args.no_audio):
        parser.error('--download-queue requires --events --day --sd-flow app; no other download or match mode')
    if args.retry_due and (args.download_queue is None or args.config is None):
        parser.error('--retry-due requires configured camera and --download-queue')
    if args.match_queue is not None and (not args.events or args.download_photo):
        parser.error('--match-queue requires --events and disallows downloads')
    if args.download_photo and not args.events:
        parser.error('--download-photo requires --events')
    if (args.no_live_wait or args.no_audio) and not args.events:
        parser.error('Experimental stream options require --events')
    if args.no_audio and args.sd_flow != 'app':
        parser.error('--no-audio requires --sd-flow app')
    if args.native_filename and args.download_photo != 'original':
        parser.error('--native-filename requires --download-photo original')
    if args.photo_time is not None:
        if not args.download_photo or args.photo_time.utcoffset() is None:
            parser.error('--photo-time requires --download-photo and an explicit UTC offset')
        if args.photo_time.microsecond:
            parser.error('--photo-time must identify a whole second')
    if args.reference_size is not None or args.reference_sha256 is not None:
        if (args.download_photo != 'original' or args.photo_time is None
                or args.reference_size is None or not 0 < args.reference_size <= MAX_SIZE
                or args.reference_sha256 is None or len(args.reference_sha256) != 64
                or any(c not in '0123456789abcdefABCDEF' for c in args.reference_sha256)):
            parser.error('Reference test requires --download-photo original, --photo-time, '
                         '--reference-size and a 64-digit --reference-sha256')
    sdk_version = version('p4p-camera-sdk')
    print(f'SDK version: {sdk_version}')
    if sdk_version != '0.1.16':
        parser.error('Install the pinned SDK with python -m pip install -r requirements.txt')
    try:
        account, password = read_credentials()
    except ValueError:
        parser.error('Account and password are required')
    logging.disable(logging.CRITICAL)
    stage = 'account login / device discovery'
    resources = contextlib.ExitStack()
    retry_db = None
    retry_ids = None
    on_failure = None
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            if args.camera_uid is not None:
                device = asyncio.run(get_device_by_uid(account, password, args.camera_uid))
            else:
                device = asyncio.run(CredentialClient(account, password).get_device(index=args.index))
        print('Account login and device discovery successful.')
        if args.camera_uid is not None:
            if device.device_uid != args.camera_uid:
                raise RuntimeError('Configured camera mismatch')
            print('Configured camera UID verified.')
        if not (args.events or args.sdk_events or args.sd_status):
            return 0
        stage = 'camera relay session / SD status' if args.sd_status else 'camera relay session / SD event listing'
        end = int(time.time())
        begin = end - args.hours * 3600
        if args.day:
            tz = ZoneInfo(args.tz)
            begin = int(dt.datetime.combine(args.day, dt.time.min, tzinfo=tz).timestamp())
            end = int(dt.datetime.combine(args.day + dt.timedelta(days=1), dt.time.min, tzinfo=tz).timestamp())
        if args.match_queue is not None:
            stage = 'read-only queue selection'
            cloud_times = queued_times(args.match_queue, device.device_uid, begin - 4, end + 4)
            if not any(begin <= t < end for t in cloud_times):
                print('No queued cloud events for selected camera and interval; no relay session.')
                return 1
            match_begin, match_end = begin, end
            begin, end = begin - 6, end + 6
            stage = 'camera relay session / SD event listing'
        if args.download_queue is not None:
            stage = 'batch queue selection and local verification'
            resources.enter_context(batch_lock(args.download_queue))
            batch_begin, batch_end = begin, end
            batch_rows = load_rows(args.download_queue, device.device_uid, begin, end)
            check_existing(args.download_queue, device.device_uid, batch_rows, begin, end, validate_image)
            pending = sum(eligible(row, begin, end) for row in batch_rows)
            print(f'Batch pending eligible originals: {pending}; limit={args.batch_limit}')
            if args.retry_due:
                with args.config.open('rb') as source:
                    retry_policy = parse_retry(tomllib.load(source).get('download_retry'))
                retry_threshold = load_alerts(args.config).threshold('camera')
                retry_db = resources.enter_context(contextlib.closing(sqlite3.connect(args.download_queue, timeout=10)))
                init_retry(retry_db)
                now = int(time.time())
                sync_download_health(retry_db, device.device_uid, now, retry_threshold)
                retry_ids = due_ids(retry_db, device.device_uid, batch_rows, begin, end, now, args.batch_limit)
                pending = len(retry_ids)
                print(f'Retry selection: due={pending}; initial={retry_policy.initial_minutes}m; cap={retry_policy.max_minutes}m')
                def on_failure(ident, reason):
                    record_failure(retry_db, device.device_uid, ident, int(time.time()), reason, retry_policy)

            if not pending:
                print('No eligible pending originals; no relay session, no SMTP.')
                return 0
            begin, end = begin - 6, end + 6
            stage = 'camera relay session / SD event listing'
        session = DiagnosticRelay(device.device_uid, device.device_password)
        started = time.monotonic()
        session.started = started
        print('H4 compatibility: corrected P4P tail permutations; encoded outbound KCP; native RDT control recovery')
        print(f'SD flow: {args.sd_flow}; KCP receive window: {args.kcp_window}; '
              f'wait for live: {not args.no_live_wait}; AVCTRL audio: {not args.no_audio}')
        if args.events or args.sdk_events:
            print(f'Query UTC: {dt.datetime.fromtimestamp(begin, dt.timezone.utc).isoformat()}'
              f' to {dt.datetime.fromtimestamp(end, dt.timezone.utc).isoformat()}')
        if retry_db is not None:
            reserve(retry_db, device.device_uid, retry_ids, int(time.time()), retry_policy)
        try:
            with relay_compat(session):
                with session:
                    if args.kcp_window != 256:
                        session.kcp.set_window_size(128, args.kcp_window)
                    if args.sd_status:
                        session.wait_for_live_stream()
                        session.phase = 'SD status'
                        session.send_ioctrl(0, IOTYPE_GET_SD_STATUS_REQ, build_get_sd_status())
                        for iotype, _ in session.poll_ioctrl(timeout=10):
                            if iotype == IOTYPE_GET_SD_STATUS_RSP:
                                break
                        session.phase = 'settings read'
                        session.send_ioctrl(0, IOTYPE_GET_ADVANCE_SETTINGS_REQ, bytes(4))
                        for iotype, _ in session.poll_ioctrl(timeout=10):
                            if iotype == IOTYPE_GET_ADVANCE_SETTINGS_RSP:
                                break
                    elif args.sdk_events:
                        events = SdCardClient(session).list_events(begin, end)
                    else:
                        events = list_events_staged(session, begin, end, flow=args.sd_flow,
                                                   wait_live=not args.no_live_wait,
                                                   with_audio=not args.no_audio)
                        if args.download_queue is not None:
                            stage = 'queue original batch download'
                            batch_missing = download_batch(session, args.download_queue,
                                                           device.device_uid, batch_rows,
                                                           batch_begin, batch_end, events,
                                                           args.output_dir, args.batch_limit,
                                                           download_photo, validate_image,
                                                           retry_ids=retry_ids, on_failure=on_failure)
                        elif args.download_photo:
                            stage = 'experimental JPEG download'
                            photos = [e for e in events if e.length == 65535]
                            if args.photo_time is not None:
                                target = int(args.photo_time.timestamp())
                                photos = [e for e in photos if e.start_time == target]
                                if len(photos) != 1:
                                    session.stage_notes.append('Explicit photo time did not select exactly one photo.')
                                    raise RuntimeError('Photo selection ambiguous or missing')
                            else:
                                photos = [e for e in photos if e.event_type == 4]
                            if not photos:
                                session.stage_notes.append('No matching photo candidate.')
                                raise RuntimeError('No photo candidate')
                            event = max(photos, key=lambda e: e.start_time)
                            kind = 2 if args.download_photo == 'thumbnail' else 3
                            destination = args.output_dir / f'event{event.event_type}_{event.start_time}_{args.download_photo}.jpg'
                            if destination.exists() and not args.native_filename:
                                raise FileExistsError('Local destination already exists')
                            session.stage_notes.append(f'Photo candidate: timestamp={event.start_time}, event_type={event.event_type}, file_type={kind}, length={event.length}, src_event={event.src_event}, src_status={event.src_status}')
                            download_photo(session, event, kind, destination,
                                           reference_size=args.reference_size,
                                           reference_sha256=args.reference_sha256,
                                           preserve_filename=args.native_filename)
        except TimeoutError:
            if retry_db is not None and stage == 'camera relay session / SD event listing':
                for ident in retry_ids:
                    on_failure(ident, 'relay_timeout')
            raise
        finally:
            if retry_db is not None:
                sync_download_health(retry_db, device.device_uid, int(time.time()), retry_threshold)
            print(f'Relay / SD query elapsed: {time.monotonic() - started:.1f} s')
            session.report()
            for note in getattr(session, 'stage_notes', []):
                print(note)
        if args.download_queue is not None:
            print('Batch session closed. No SMTP.')
            return 1 if batch_missing else 0
        if args.sd_status:
            for label, expected in [('SD status', IOTYPE_GET_SD_STATUS_RSP),
                                    ('Advanced settings', IOTYPE_GET_ADVANCE_SETTINGS_RSP)]:
                found = any(kind == expected for (_, kind) in session.frames)
                print(f'{label}: {"response received" if found else "no explicit response decoded"}')
            return 0
        if args.match_queue is not None:
            counts = Counter()
            for cloud, status, sd in match_events(cloud_times, events):
                if not match_begin <= cloud < match_end:
                    continue
                counts[status] += 1
                when = dt.datetime.fromtimestamp(cloud, dt.timezone.utc).isoformat()
                if sd is None:
                    print(f'Match: cloud={when} | {status}')
                else:
                    sd_when = dt.datetime.fromtimestamp(sd, dt.timezone.utc).isoformat()
                    print(f'Match: cloud={when} | SD={sd_when} | delta={sd-cloud:+d}s')
            print(f'Match summary: matched={counts["matched"]}, missing={counts["missing"]}, ambiguous={counts["ambiguous"]}')
            print('Read-only matching test: no photo download, no database changes, no SMTP.')
            return 1 if counts['missing'] or counts['ambiguous'] else 0
        print(f'Events returned: {len(events)}')
        if not events:
            if args.events:
                print('No recordings reported in the requested time range.')
            else:
                print('No events decoded; SD card may still contain recordings.')
        for event in sorted(events, key=lambda e: e.start_time):
            stamp = dt.datetime.fromtimestamp(event.start_time, dt.timezone.utc).isoformat()
            print(f'{stamp} | type={event.event_type} | length={event.length}')
        return 0
    except Exception as exc:
        print(f'Failed during {stage}: {type(exc).__name__}. Raw diagnostic details suppressed.')
        return 1
    finally:
        resources.close()


if __name__ == '__main__':
    raise SystemExit(main())
