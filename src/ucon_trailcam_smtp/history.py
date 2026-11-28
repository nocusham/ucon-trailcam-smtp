"""Preview or explicitly export one configured camera's historical photo events."""
import argparse
import asyncio
from collections import Counter
from contextlib import closing
import datetime as dt
import logging
import json
from pathlib import Path
import sqlite3
import time
from zoneinfo import ZoneInfo

from ucon_trailcam_smtp.camera_selection import profile_uid, select_device
from ucon_trailcam_smtp.camera_smtp import load_profiles
from ucon_trailcam_smtp.cloud_intake import MAX_STEP, login_blocked
from ucon_trailcam_smtp.queue_download import batch_lock
from ucon_trailcam_smtp.event_metadata import event_metadata
from ucon_trailcam_smtp.service_download import effective_batch_limit
from ucon_trailcam_smtp.history_receipts import observations
from ucon_trailcam_smtp.safe_diagnostics import cloud_fields, error_fields


def date_range(first, last, timezone, now):
    """Inclusive local calendar dates, half-open UTC interval."""
    if first > last:
        raise ValueError('Reversed historical date range')
    tz = ZoneInfo(timezone)
    begin = int(dt.datetime.combine(first, dt.time.min, tzinfo=tz).timestamp())
    end = int(dt.datetime.combine(last + dt.timedelta(days=1), dt.time.min, tzinfo=tz).timestamp())
    end = min(end, now + 1)
    if begin < 0 or begin >= end:
        raise ValueError('Historical range must contain elapsed time after Unix epoch')
    return begin, end


def local_events(db, uid, begin, end):
    rows = db.execute("SELECT itemid,et_utc,state FROM events WHERE camera_uid=? "
                      "AND et_utc>=? AND et_utc<? AND json_extract(metadata_json,'$.type')=1",
                      (uid,begin,end)).fetchall()
    known = {'pending','downloaded','sent','uncertain','expired','sent_history'}
    if any(state not in known for _,_,state in rows):
        raise ValueError('Unexpected local event state')
    local = {ident:(stamp,state) for ident,stamp,state in rows}
    for ident,(stamp,state,_) in observations(db,uid,begin,end).items():
        prior = local.get(ident)
        if prior and prior[0]!=stamp:
            raise ValueError('Historical receipt identity conflict')
        if prior and prior[1]=='uncertain':
            state='uncertain'
        elif prior and prior[1]=='sent' and state!='uncertain':
            state='sent'
        local[ident]=(stamp,state)
    return local


async def collect_preview(db, uid, begin, end, query, *, emit=print, include_events=False):
    """Merge bounded cloud windows without persisting or changing a queue."""
    if not 0 <= begin < end:
        raise ValueError('Invalid historical interval')
    local = local_events(db,uid,begin,end)
    remote = {}
    cursor = begin
    windows = 0
    while cursor < end:
        boundary = min(end,cursor+MAX_STEP)
        result = await query(uid,cursor,boundary)
        if not isinstance(result,dict) or not isinstance(result.get('items'),list):
            raise ValueError('Invalid cloud event list')
        for item in result['items']:
            if not isinstance(item,dict) or item.get('uid',item.get('device_uid')) != uid:
                continue
            if type(item.get('type')) is not int or item['type'] != 1:
                continue
            stamp = item.get('et_utc')
            ident = item.get('itemid')
            if type(stamp) is not int or not 0 < stamp <= 4102444800:
                raise ValueError('Invalid historical photo timestamp')
            if not begin <= stamp < end:
                continue
            if not isinstance(ident,str) or not ident.strip() or len(ident)>512:
                raise ValueError('Invalid historical photo identity')
            if ident in remote and remote[ident][0] != stamp:
                raise ValueError('Cloud event identity conflict')
            existing = db.execute('SELECT et_utc,state FROM events WHERE camera_uid=? AND itemid=?',
                                  (uid,ident)).fetchone()
            if (existing is not None and (existing[0] != stamp or ident not in local)) or (
                    ident in local and local[ident][0]!=stamp):
                raise ValueError('Local and cloud event identity conflict')
            raw = json.dumps(event_metadata(item), ensure_ascii=False, allow_nan=False)
            if len(raw.encode('utf-8')) > 1_048_576:
                raise ValueError('Historical metadata exceeds size limit')
            remote[ident] = (stamp, raw)
        cursor = boundary
        windows += 1
        if windows % 24 == 0:
            emit(f'History preview: processed {windows} cloud windows.')
    counts = Counter(state for _,state in local.values())
    counts['unknown_history'] = len(remote.keys() - local.keys())
    counts['cloud_only'] = counts['unknown_history']
    counts['local_only'] = len(local.keys() - remote.keys())
    counts['cloud_and_local'] = len(remote.keys() & local.keys())
    counts['total'] = len(local.keys() | remote.keys())
    if include_events:
        return counts, local, remote
    return counts


async def run(args):
    # Lazy imports keep --help offline and independent of live credentials.
    import httpx
    from ucon_trailcam_smtp.cloud_api import discover_devices, list_cloud_events
    from ucon_trailcam_smtp.ucon_auth import read_credentials
    profiles = load_profiles(args.config)
    uid = profile_uid(profiles,args.camera)
    profile = next(p for p in profiles if p.uid == uid)
    limit = effective_batch_limit(profile,args.batch_limit)
    begin,end = date_range(args.first,args.last,args.tz,int(time.time()))
    with batch_lock(args.queue_db), closing(sqlite3.connect(
            args.queue_db.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        if login_blocked(db):
            print('Login blocked; correct credentials and explicitly resume using the service command first.')
            return 1
        account,password = read_credentials(interactive=False)
        async with httpx.AsyncClient(timeout=30,follow_redirects=False) as client:
            headers,devices = await discover_devices(client,account,password)
            device = select_device(devices,uid=uid)
            result = await collect_preview(db,uid,begin,end,
                lambda u,b,e: list_cloud_events(client,headers,u,b,e), include_events=args.download)
        if args.download:
            from ucon_trailcam_smtp.history_download import export_history, relay_batch
            from functools import partial
            from importlib.metadata import version
            if version('p4p-camera-sdk') != '0.1.16':
                raise ValueError('Pinned SDK required')
            counts, local, remote = result
            return export_history(db, uid, local, remote, args.output_dir, limit,
                                  partial(relay_batch, device))
        counts = result
    print(f'History preview: camera={args.camera}; dates={args.first} through {args.last}; tz={args.tz}')
    for key in ('total','pending','downloaded','sent','sent_history','uncertain','expired',
                'unknown_history','cloud_only','local_only','cloud_and_local'):
        print(f'  {key}={counts[key]}')
    print('Local states are not file integrity checks. Cloud/SD historical completeness is unverified.')
    print('Unknown history is not proof of non-delivery. Preview only; no images downloaded, no SMTP, no queue changes.')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True,type=Path)
    parser.add_argument('--queue-db',required=True,type=Path)
    parser.add_argument('--camera',required=True,help='One enabled configured camera name')
    parser.add_argument('--from',dest='first',required=True,type=dt.date.fromisoformat)
    parser.add_argument('--to',dest='last',required=True,type=dt.date.fromisoformat,
                        help='Inclusive local end date')
    parser.add_argument('--tz',default='Europe/Berlin')
    parser.add_argument('--download',action='store_true',help='Export verified originals; no SMTP')
    parser.add_argument('--output-dir',type=Path,help='Private parent directory for a new export')
    parser.add_argument('--batch-limit',type=int,help='Override sequential originals per relay (1–100)')
    args = parser.parse_args(argv)
    if args.download != (args.output_dir is not None):
        parser.error('--download requires --output-dir; preview does not use it')
    if args.batch_limit is not None and (not args.download or not 1 <= args.batch_limit <= 100):
        parser.error('--batch-limit requires --download and range 1–100')
    logging.disable(logging.CRITICAL)
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f'History stopped; {error_fields(exc)} {cloud_fields(exc)}. No queue changes; partial exports may remain.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
