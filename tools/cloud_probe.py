"""One-shot, experimental account-scoped event query; no P4P connection."""
import argparse
import asyncio
import datetime as dt
import re
from pathlib import Path
from importlib.metadata import version
from functools import partial
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx
from ucon_trailcam_smtp.ucon_auth import read_credentials
from ucon_trailcam_smtp.cloud_image import ImageError, reference_scheme, select_latest, fetch_image
from ucon_trailcam_smtp.event_metadata import select_event, save_metadata
from ucon_trailcam_smtp.event_queue import ingest_events, QueueError
from ucon_trailcam_smtp.cloud_watch import watch
from ucon_trailcam_smtp.camera_selection import profile_uid
# Re-export the original API helpers for legacy diagnostic callers.
from ucon_trailcam_smtp.cloud_api import (ApiError, post_json, discover_devices, list_devices,
                       authenticate, get_device_by_uid, list_cloud_events)


async def query_events(client, account, password, index, begin, end, *, schema=False, image_dir=None, event_time=None, export_event=None, queue_db=None, camera_uid=None):
    headers, uid = await authenticate(client, account, password, index, camera_uid=camera_uid)
    result = await list_cloud_events(client, headers, uid, begin, end)
    items = result['items']
    if queue_db is not None:
        added, known, rejected, pending = ingest_events(queue_db, uid, items)
        print(f'Queue: new={added}, known={known}, rejected={rejected}, pending={pending}')
    if schema:
        print_event_schema(result, uid)
    if image_dir is not None or export_event is not None:
        item = select_latest(items, uid) if event_time is None else select_event(items, uid, event_time)
    if export_event is not None:
        save_metadata(export_event, item)
        print(f'Event metadata saved locally: {export_event}')
    if image_dir is not None:
        print('Cloud image test: API URL, public destinations only, no account headers.')
        async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False,
                                     limits=httpx.Limits(max_keepalive_connections=0)) as image_client:
            dest, size, digest, width, height = await fetch_image(image_client, item, image_dir)
        print(f'Cloud image decoded: {width}x{height}, {size} bytes; SHA256={digest}')
        print(f'Cloud image saved locally: {dest}')
    return summarize(items, uid)


def describe_fields(value, prefix='', depth=0):
    """Bounded structural diagnostics only; never return scalar values."""
    if depth > 5:
        yield prefix, 'depth limit'
        return
    if isinstance(value, dict):
        yield prefix or 'root', f'object ({len(value)} fields)'
        for key, child in list(value.items())[:80]:
            # Do not print arbitrary map keys that may be identifiers or URLs.
            safe = (key if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,23}', key)
                    and not re.search(r'[0-9]{5,}', key) else '[redacted key]')
            yield from describe_fields(child, f'{prefix}.{safe}' if prefix else safe, depth + 1)
    elif isinstance(value, list):
        yield prefix, f'array ({len(value)} items)'
        for child in value[:3]:
            yield from describe_fields(child, f'{prefix}[]', depth + 1)
    elif isinstance(value, str):
        kind = 'empty string' if not value else 'string'
        if value:
            try:
                parsed = urlsplit(value)
                if parsed.scheme.lower() in ('https', 'http') and parsed.hostname:
                    kind = f'{parsed.scheme.lower()} URL'
                elif value.lstrip().startswith(('{', '[')):
                    kind = 'possible embedded JSON string'
                elif '/' in value:
                    kind = 'string containing slash (possible path)'
            except ValueError:
                pass
        yield prefix, f'{kind}, length={len(value)}'
    elif value is None:
        yield prefix, 'null'
    else:
        yield prefix, type(value).__name__


def print_event_schema(result, uid):
    """Only examine the selected device's records, never other account data."""
    items = result.get('items', [])
    own = [i for i in items if isinstance(i, dict)
           and i.get('uid', i.get('device_uid')) == uid]
    print('Event API structure (field names/types only, values suppressed):')
    # Response-level metadata can contain cursors and tokens; show shape only.
    meta = {k: v for k, v in result.items() if k != 'items'}
    for path, kind in describe_fields(meta, 'data'):
        print(f'  {path}: {kind}')
    for index, item in enumerate(own[:5], 1):
        print(f'  Matching item {index}:')
        for path, kind in describe_fields(item, 'item'):
            print(f'    {path}: {kind}')


def summarize(items, uid):
    """Report only matching-device counts and safe event metadata."""
    rows = []
    unverified = 0
    for item in items:
        if not isinstance(item, dict) or item.get('uid', item.get('device_uid')) != uid:
            unverified += 1
            continue
        stamp = item.get('et_utc')
        if type(stamp) is not int or not 0 <= stamp <= 4102444800:
            stamp = None
        image = item.get('img_url')
        has_image = reference_scheme(image) is not None
        rows.append((stamp, has_image))
    return rows, unverified


async def run(args, account, password, begin, end):
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        if args.watch:
            return await watch(client, account, password, args.index, args.queue_db,
                               authenticate=partial(authenticate, camera_uid=args.camera_uid), list_events=list_cloud_events,
                               api_error=ApiError, cycles=args.cycles, interval=args.interval,
                               hours=args.hours, overlap=args.overlap)
        return await query_events(client, account, password, args.index, begin, end, schema=args.schema,
                                  image_dir=args.output_dir if args.download_image else None,
                                  event_time=int(args.event_time.timestamp()) if args.event_time else None,
                                  export_event=args.export_event, queue_db=args.queue_db, camera_uid=args.camera_uid)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', type=int, default=None, help='Legacy diagnostic camera index')
    parser.add_argument('--config', type=Path, help='Local camera profile configuration')
    parser.add_argument('--camera', help='Enabled configured camera name')
    window = parser.add_mutually_exclusive_group()
    window.add_argument('--day', type=dt.date.fromisoformat)
    window.add_argument('--hours', type=int, default=24)
    parser.add_argument('--tz', default='Europe/Berlin')
    parser.add_argument('--schema', action='store_true',
                        help='Show event field names, types and string classifications only')
    parser.add_argument('--download-image', action='store_true',
                        help='Try one latest matching cloud image from its API URL')
    parser.add_argument('--output-dir', type=Path, default=Path('media/cloud'))
    parser.add_argument('--event-time', type=dt.datetime.fromisoformat,
                        help='Exact cloud et_utc timestamp, including UTC offset')
    parser.add_argument('--export-event', type=Path,
                        help='Save six selected event fields to a new JSON file')
    parser.add_argument('--queue-db', type=Path,
                        help='Discovery only: persist matching events in a test SQLite database')
    parser.add_argument('--watch', action='store_true', help='Bounded discovery-only polling test')
    parser.add_argument('--cycles', type=int, default=6)
    parser.add_argument('--interval', type=int, default=60)
    parser.add_argument('--overlap', type=int, default=300)
    args = parser.parse_args()
    if args.watch and (args.queue_db is None or args.day or args.schema or args.download_image or args.export_event or args.event_time):
        parser.error('--watch requires --queue-db and rolling --hours; no other operations')
    if not 1 <= args.cycles <= 1000 or not 10 <= args.interval <= 900 or not 0 <= args.overlap <= 86400:
        parser.error('cycles 1–1000, interval 10–900 seconds, overlap 0–86400 seconds')
    if args.queue_db is not None and (args.download_image or args.export_event):
        parser.error('--queue-db cannot be combined with image download or event export')
    if args.event_time is not None and (args.event_time.utcoffset() is None or args.event_time.microsecond):
        parser.error('--event-time requires a whole second with explicit UTC offset')
    if args.export_event is not None and args.event_time is None:
        parser.error('--export-event requires --event-time to identify the correct event')
    if args.event_time is not None and not (args.export_event or args.download_image):
        parser.error('--event-time requires --export-event or --download-image')
    if bool(args.config) != bool(args.camera) or (args.config and args.index is not None):
        parser.error('Use --config and --camera together, without --index')
    args.camera_uid = None
    if args.config:
        from ucon_trailcam_smtp.camera_smtp import load_profiles
        try:
            args.camera_uid = profile_uid(load_profiles(args.config), args.camera)
        except Exception:
            parser.error('Invalid configuration or camera missing/disabled')
    args.index = 0 if args.index is None else args.index
    if args.index < 0 or not 1 <= args.hours <= 168:
        parser.error('index must be nonnegative; hours must be 1–168')
    if version('p4p-camera-sdk') != '0.1.16':
        parser.error('Use the pinned SDK version 0.1.16')
    end = int(dt.datetime.now(dt.timezone.utc).timestamp())
    begin = end - args.hours * 3600
    if args.day:
        try:
            tz = ZoneInfo(args.tz)
        except Exception:
            parser.error('Invalid time zone')
        begin = int(dt.datetime.combine(args.day, dt.time.min, tzinfo=tz).timestamp())
        end = int(dt.datetime.combine(args.day + dt.timedelta(days=1), dt.time.min, tzinfo=tz).timestamp())
    try:
        account, password = read_credentials()
        print('Experimental cloud event query; no P4P/UDP camera session.')
        result = asyncio.run(run(args, account, password, begin, end))
        if args.watch:
            return result
        rows, unverified = result
    except KeyboardInterrupt:
        print('Stopped by user; committed queue entries retained.')
        return 130
    except (ApiError, ImageError, QueueError) as exc:
        print(str(exc))
        return 1
    except Exception as exc:
        print(f'Cloud probe failed: {type(exc).__name__}. Details suppressed.')
        return 1
    print(f'Matching-device events: {len(rows)}; HTTP(S) image references: {sum(has for _, has in rows)}')
    print(f'Unverified/unmatched items ignored: {unverified}')
    for stamp, has_image in sorted(rows, key=lambda row: row[0] if row[0] is not None else -1):
        when = dt.datetime.fromtimestamp(stamp, dt.timezone.utc).isoformat() if stamp is not None else 'unknown'
        print(f'{when} | image reference: {"yes" if has_image else "no"}')
    print('No image URL, token, device ID or raw API response printed.')
    if not args.download_image:
        print('No image downloaded.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
