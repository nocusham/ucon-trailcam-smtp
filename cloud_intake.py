"""Bounded persistent cloud intake; deliberately no P4P or SMTP operations."""
import argparse
import asyncio
import datetime as dt
import time
from contextlib import closing
from pathlib import Path

from health_alerts import init_health, observe
from safe_diagnostics import cloud_fields, error_fields
from camera_telemetry import REFRESH_SECONDS, init_telemetry, record_snapshot


MAX_STEP = 3600
OVERLAP = 300


def init_intake(db, uids, now):
    init_health(db)
    with db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('''CREATE TABLE IF NOT EXISTS cloud_runtime (
            id INTEGER PRIMARY KEY CHECK(id=1), failures INTEGER NOT NULL, next_due INTEGER NOT NULL)''')
        if db.execute('SELECT 1 FROM cloud_runtime').fetchone() is None:
            if db.execute('SELECT 1 FROM events LIMIT 1').fetchone():
                raise ValueError('Use a new intake database, not a historical test queue')
            db.execute('INSERT INTO cloud_runtime VALUES (1,0,0)')
        db.execute('''CREATE TABLE IF NOT EXISTS cloud_cursors (
            camera_uid TEXT PRIMARY KEY, start_utc INTEGER NOT NULL, last_end INTEGER NOT NULL)''')
        db.executemany('INSERT OR IGNORE INTO cloud_cursors VALUES (?,?,?)',
                       [(uid, now, now) for uid in uids])


def login_blocked(db):
    return db.execute("SELECT 1 FROM health_incidents WHERE category='login' AND scope='ucon' "
                      "AND blocked=1 AND recovered_at IS NULL").fetchone() is not None


def resume_login(db):
    """Explicit operator acknowledgement after correcting credentials; no secrets stored."""
    with db:
        db.execute("UPDATE health_incidents SET blocked=0 WHERE category='login' AND scope='ucon'")
        db.execute('UPDATE cloud_runtime SET failures=0,next_due=0 WHERE id=1')


def window(db, uid, now):
    start, last = db.execute('SELECT start_utc,last_end FROM cloud_cursors WHERE camera_uid=?', (uid,)).fetchone()
    if now < last:
        raise ValueError('Clock moved behind persisted cloud cursor')
    return max(start, last - OVERLAP), min(now, last + MAX_STEP)


def photo_items(items, uid, begin, end):
    """Only H4 candidate photo events in the requested interval, never historical imports."""
    return [i for i in items if isinstance(i, dict) and i.get('uid', i.get('device_uid')) == uid
            and type(i.get('type')) is int and i['type'] == 1
            and type(i.get('et_utc')) is int and begin <= i['et_utc'] <= end]


class Intake:
    def __init__(self, db, uids, *, discover, query, store, api_error, interval=60, emit=print,
                 refresh_devices=None, on_devices=None):
        self.db, self.uids = db, tuple(uids)
        self.discover, self.query, self.store = discover, query, store
        self.api_error, self.interval, self.emit = api_error, interval, emit
        self.session = None
        self.refresh_devices, self.on_devices = refresh_devices, on_devices
        self.last_refresh = None

    def backoff(self, now):
        failures, = self.db.execute('SELECT failures FROM cloud_runtime WHERE id=1').fetchone()
        delay = min(900, self.interval * 2 ** min(failures + 1, 4))
        with self.db:
            self.db.execute('UPDATE cloud_runtime SET failures=?,next_due=? WHERE id=1', (failures + 1, now + delay))
        return failures + 1, delay

    async def cycle(self, now):
        db = self.db
        if login_blocked(db):
            self.emit('Login blocked (20005); correct credentials and explicitly resume. No cloud requests.')
            return 'blocked'
        prior_failures, due = db.execute('SELECT failures,next_due FROM cloud_runtime WHERE id=1').fetchone()
        if now < due:
            self.emit('Cloud retry not due; no cloud requests.')
            return 'deferred'
        fresh_devices = False
        covered = set()
        try:
            if self.session is None:
                self.session = await self.discover()
                fresh_devices = True
                observe(db, 'login', 'ucon', healthy=True, now=now)
            headers, devices = self.session
            if (not fresh_devices and self.refresh_devices is not None
                    and (self.last_refresh is None or now - self.last_refresh >= REFRESH_SECONDS)):
                devices = await self.refresh_devices(headers)
                self.session = (headers, devices)
                fresh_devices = True
            if not isinstance(devices, list):
                raise self.api_error('device discovery: invalid list', stage='device discovery', diagnostic_kind='invalid_schema')
            for uid in self.uids:
                if sum(isinstance(d, dict) and d.get('device_uid') == uid for d in devices) != 1:
                    raise self.api_error('Configured camera missing or ambiguous', stage='device discovery', diagnostic_kind='camera_selection')
                begin, end = window(db, uid, now)
                if end <= begin:
                    self.emit('Cloud intake baseline initialized; no elapsed interval yet.')
                    continue
                result = await self.query(headers, uid, begin, end)
                items = photo_items(result['items'], uid, begin, end)
                added, known, rejected, pending = self.store(uid, items)
                if rejected:
                    raise self.api_error('Cloud photo metadata rejected; cursor retained', stage='cloud event list', diagnostic_kind='metadata_rejected')
                # Store commits first. If interrupted before cursor commit, overlap/dedup replay is safe.
                with db:
                    db.execute('UPDATE cloud_cursors SET last_end=? WHERE camera_uid=?', (end, uid))
                if end == now:
                    covered.add(uid)
                self.emit(f'Cloud intake: new={added}, known={known}, pending={pending}, window={end-begin}s')
        except self.api_error as exc:
            stage = getattr(exc, 'stage', None)
            code = getattr(exc, 'api_code', None)
            if stage == 'login':
                observe(db, 'login', 'ucon', healthy=False, now=now, code=code, blocked=code == 20005)
            else:
                if stage == 'device discovery':
                    observe(db, 'login', 'ucon', healthy=True, now=now)
                    self.session = None
                observe(db, 'api', 'ucon', healthy=False, now=now, code=code)
            if getattr(exc, 'http_status', None) in (401, 403):
                self.session = None
            failures, delay = self.backoff(now)
            blocked = login_blocked(db)
            stamp = dt.datetime.fromtimestamp(now, dt.timezone.utc).isoformat()
            action = 'manual_resume_required' if blocked else f'retry_in={delay}s'
            self.emit(f'Cloud check failed; {cloud_fields(exc)} failures={failures} {action} utc={stamp}; cursor retained.')
            return 'blocked' if blocked else 'error'
        if fresh_devices:
            if self.on_devices is not None:
                self.on_devices(devices, now, covered)
            self.last_refresh = now
        observe(db, 'api', 'ucon', healthy=True, now=now)
        with db:
            db.execute('UPDATE cloud_runtime SET failures=0,next_due=0 WHERE id=1')
        if prior_failures:
            stamp = dt.datetime.fromtimestamp(now, dt.timezone.utc).isoformat()
            self.emit(f'Cloud recovered; previous_failures={prior_failures} utc={stamp}; retry state cleared.')
        return 'ok'


async def run(args):
    import httpx
    from camera_smtp import load_profiles
    from cloud_api import ApiError, discover_devices, list_cloud_events, list_devices
    from event_queue import open_queue, ingest_events
    from queue_download import batch_lock
    from ucon_auth import read_credentials
    profiles = [p for p in load_profiles(args.config) if p.enabled]
    if not profiles:
        raise ValueError('No enabled cameras')
    # Create privately before locking; do not promote historical queues.
    with closing(open_queue(args.queue_db)):
        pass
    with batch_lock(args.queue_db), closing(open_queue(args.queue_db)) as db:
        init_intake(db, [p.uid for p in profiles], int(time.time()))
        init_telemetry(db)
        if args.resume_login:
            resume_login(db)
        if login_blocked(db):
            print('Login blocked (20005); correct credentials and use --resume-login. No cloud requests.')
            return 1
        account, password = read_credentials(interactive=False)
        def on_devices(devices, now, covered):
            for p in profiles:
                device, = [d for d in devices if isinstance(d, dict) and d.get('device_uid') == p.uid]
                photo, = db.execute("SELECT MAX(et_utc) FROM events WHERE camera_uid=? AND et_utc<=? "
                                    "AND json_extract(metadata_json,'$.type')=1", (p.uid, now)).fetchone()
                status = record_snapshot(db, p.uid, device, now, enabled=p.inactivity_warning,
                                         days=p.inactivity_days, photo_utc=photo,
                                         coverage_end=now if p.uid in covered else None)
                print(f'Camera {p.name}: cloud telemetry saved; inactivity={status}')
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            intake = Intake(db, [p.uid for p in profiles],
                            discover=lambda: discover_devices(client, account, password),
                            query=lambda h, u, b, e: list_cloud_events(client, h, u, b, e),
                            store=lambda u, items: ingest_events(args.queue_db, u, items),
                            api_error=ApiError, interval=args.interval,
                            refresh_devices=lambda h: list_devices(client, h), on_devices=on_devices)
            results = []
            for i in range(args.cycles):
                status = await intake.cycle(int(time.time()))
                results.append(status)
                if status == 'blocked':
                    break
                if i + 1 < args.cycles:
                    await asyncio.sleep(args.interval)
            print(f'Cloud intake complete: successful={results.count("ok")}/{args.cycles}; no P4P or SMTP.')
            return int(any(s != 'ok' for s in results))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--queue-db', required=True, type=Path)
    parser.add_argument('--cycles', type=int, default=1)
    parser.add_argument('--interval', type=int, default=60)
    parser.add_argument('--resume-login', action='store_true', help='Explicitly release persisted login block')
    args = parser.parse_args()
    if not 1 <= args.cycles <= 1000 or not 10 <= args.interval <= 900:
        parser.error('cycles 1–1000; interval 10–900 seconds')
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f'Cloud intake stopped; {error_fields(exc)}.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
