"""Sequential Ucon service, explicit opt-in for each network action."""
import argparse
import asyncio
import logging
import time
import tomllib
from contextlib import closing
from functools import partial
from importlib.metadata import version
from pathlib import Path

from cloud_intake import Intake, init_intake, resume_login
from camera_telemetry import init_telemetry, record_snapshot, fresh_scopes
from download_retry import init_retry, parse_retry, reserve, record_failure, sync_download_health
from health_alerts import load_alerts, dispatch_due, due_notices, smtp_sender
from service_cycle import run_cycle
from service_download import plan_download
from media_retention import parse_retention, cleanup


def download_one(db, args, profile, devices, policy, settings):
    from camera_selection import select_device, relay_credentials
    from probe import DiagnosticRelay, relay_compat
    from queue_download import load_rows, download_batch
    from h4_events import list_events_staged
    from h4_download import download_photo
    from cloud_image import validate_image
    now = int(time.time())
    uid = profile.uid
    threshold = settings.threshold('camera')
    sync_download_health(db, uid, now, threshold)
    plan = plan_download(db, uid, now, args.batch_limit)
    if plan is None:
        print(f'Camera {profile.name}: no due originals; no relay.')
        return 0
    begin, end, ids = plan
    rows = load_rows(args.queue_db, uid, begin, end)
    _, password, _ = relay_credentials(select_device(devices, uid=uid))
    session = DiagnosticRelay(uid, password)
    session.started = time.monotonic()
    reserve(db, uid, ids, int(time.time()), policy)
    def failed(ident, reason):
        record_failure(db, uid, ident, int(time.time()), reason, policy)
    listing = True
    print(f'Camera {profile.name}: due={len(ids)}; opening one relay.')
    try:
        with relay_compat(session), session:
            events = list_events_staged(session, begin - 6, end + 6, flow='app')
            listing = False
            missing = download_batch(session, args.queue_db, uid, rows, begin, end,
                                     events, args.output_dir, args.batch_limit,
                                     partial(download_photo, require_native_filename=True),
                                     validate_image, retry_ids=ids, on_failure=failed)
        return int(bool(missing))
    except TimeoutError:
        if listing:
            for ident in ids:
                failed(ident, 'relay_timeout')
        print(f'Camera {profile.name}: confirmed remote timeout; retry scheduled.')
        return 1
    finally:
        sync_download_health(db, uid, int(time.time()), threshold)
        print(f'Camera {profile.name}: relay finished; elapsed={time.monotonic()-session.started:.1f}s.')


async def run(args):
    import httpx
    from camera_smtp import load_profiles, route_batch
    from cloud_probe import ApiError, discover_devices, list_devices, list_cloud_events
    from event_queue import open_queue, ingest_events
    from queue_download import batch_lock
    from smtp_probe import load_image, build_message, send_message
    from ucon_auth import read_credentials
    if version('p4p-camera-sdk') != '0.1.16':
        raise ValueError('Pinned SDK required')
    profiles = [p for p in load_profiles(args.config) if p.enabled]
    if not profiles:
        raise ValueError('No enabled cameras')
    settings = load_alerts(args.config)
    with args.config.open('rb') as source:
        raw = tomllib.load(source)
        policy = parse_retry(raw.get('download_retry'))
        retention = parse_retention(raw.get('retention'))
    if args.cleanup and not retention.enabled:
        raise ValueError('--cleanup requires retention.enabled=true')
    with closing(open_queue(args.queue_db)):
        pass
    with batch_lock(args.queue_db), closing(open_queue(args.queue_db)) as db:
        init_intake(db, [p.uid for p in profiles], int(time.time()))
        init_telemetry(db)
        init_retry(db)
        if args.resume_login:
            resume_login(db)
        cameras = {p.uid: p.name for p in profiles}
        def on_devices(devices, now, covered):
            for p in profiles:
                device, = [d for d in devices if isinstance(d, dict) and d.get('device_uid') == p.uid]
                photo, = db.execute("SELECT MAX(et_utc) FROM events WHERE camera_uid=? AND et_utc<=? "
                                    "AND json_extract(metadata_json,'$.type')=1", (p.uid, now)).fetchone()
                status = record_snapshot(db, p.uid, device, now, enabled=p.inactivity_warning,
                                         days=p.inactivity_days, photo_utc=photo,
                                         coverage_end=now if p.uid in covered else None)
                print(f'Camera {p.name}: cloud telemetry saved; inactivity={status}')
        def deliver(p):
            return route_batch(db, [p], 0, int(time.time()) + 1, send_enabled=args.send,
                               load_image=load_image, build_message=build_message, send_message=send_message)
        def alarms(status):
            now = int(time.time())
            # Photo fallback remains observation-only until completeness is verified.
            capable = {uid for uid, in db.execute("SELECT camera_uid FROM camera_telemetry WHERE source='cloud_activity'")}
            enabled = {p.uid for p in profiles if p.inactivity_warning} & capable
            scopes = fresh_scopes(db, enabled, now) if status == 'ok' else set()
            if not args.send_alerts:
                count = len(due_notices(db, settings, now, cameras, inactivity_scopes=scopes))
                print(f'Alarm preview: due={count}; no alarm SMTP.')
                return 0
            accepted, failed = dispatch_due(db, settings, now, cameras,
                                            lambda msg: smtp_sender(settings)(msg), inactivity_scopes=scopes)
            print(f'Alarms: accepted={accepted}, failed={failed}')
            return int(bool(failed))
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            async def discover():
                account, password = read_credentials(interactive=False)
                return await discover_devices(client, account, password)
            intake = Intake(db, list(cameras), discover=discover,
                            query=lambda h,u,b,e: list_cloud_events(client,h,u,b,e),
                            store=lambda u,items: ingest_events(args.queue_db,u,items),
                            api_error=ApiError, interval=args.interval,
                            refresh_devices=lambda h: list_devices(client,h), on_devices=on_devices)
            cycle = failed = 0
            next_cleanup = 0
            while args.loop or cycle < args.cycles:
                cycle += 1
                started = time.monotonic()
                print(f'Service cycle {cycle}')
                failed += await run_cycle(profiles, cloud=lambda: intake.cycle(int(time.time())),
                                          devices=lambda: intake.session[1],
                                          download=lambda p,d: download_one(db,args,p,d,policy,settings),
                                          deliver=deliver, alerts=alarms, download_enabled=args.download)
                if args.cleanup and time.monotonic() >= next_cleanup:
                    try:
                        _, _, skipped = cleanup(db, args.output_dir, retention, int(time.time()), apply=True)
                        failed += int(bool(skipped))
                    except (OSError, ValueError) as exc:
                        print(f'Retention stopped ({type(exc).__name__}); details suppressed.')
                        failed += 1
                    next_cleanup = time.monotonic() + 3600
                if args.loop or cycle < args.cycles:
                    await asyncio.sleep(max(1, args.interval - (time.monotonic() - started)))
            print(f'Service complete: cycles={cycle}, failed={failed}')
            return int(bool(failed))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--queue-db', required=True, type=Path)
    parser.add_argument('--output-dir', type=Path, default=Path('media/service'))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--cycles', type=int, default=1)
    mode.add_argument('--loop', action='store_true')
    parser.add_argument('--interval', type=int, default=60)
    parser.add_argument('--batch-limit', type=int, default=3)
    parser.add_argument('--download', action='store_true')
    parser.add_argument('--send', action='store_true')
    parser.add_argument('--send-alerts', action='store_true')
    parser.add_argument('--resume-login', action='store_true')
    parser.add_argument('--cleanup', action='store_true', help='Allow configured local image retention cleanup')
    args = parser.parse_args()
    if not 1 <= args.cycles <= 1000 or not 10 <= args.interval <= 900 or not 1 <= args.batch_limit <= 10:
        parser.error('cycles 1–1000; interval 10–900 seconds; batch-limit 1–10')
    logging.disable(logging.CRITICAL)
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f'Service stopped ({type(exc).__name__}); details suppressed.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
