"""Bounded discovery-only cloud polling test (no camera or SMTP worker)."""
import asyncio
import datetime as dt
import time

from event_queue import ingest_events


async def watch(client, account, password, index, db, *, authenticate, list_events,
                api_error, cycles=6, interval=60, hours=24, overlap=300,
                clock=time.time, sleep=asyncio.sleep, emit=print):
    session = None
    expected_uid = None
    last_end = None
    failures = successes = logins = 0
    for attempt in range(1, cycles + 1):
        try:
            if session is None:
                headers, uid = await authenticate(client, account, password, index)
                if expected_uid is not None and uid != expected_uid:
                    raise RuntimeError('Selected camera changed after login; stopping')
                expected_uid = uid
                session = (headers, uid)
                logins += 1
                emit(f'Cloud login successful; session count={logins}')
            headers, uid = session
            end = max(int(clock()), last_end or 0)
            begin = max(0, end - hours * 3600 if last_end is None else last_end - overlap)
            result = await list_events(client, headers, uid, begin, end)
            added, known, rejected, pending = ingest_events(db, uid, result['items'])
            last_end = end
            failures = 0
            successes += 1
            stamp = dt.datetime.fromtimestamp(end, dt.timezone.utc).isoformat()
            emit(f'Poll {attempt}/{cycles} {stamp}: new={added}, known={known}, '
                 f'rejected={rejected}, pending={pending}, window={end - begin}s')
        except api_error as exc:
            failures += 1
            if getattr(exc, 'http_status', None) in (401, 403):
                session = None
            emit(f'Poll {attempt}/{cycles}: {exc}')
        if attempt < cycles:
            delay = min(900, interval * 2 ** min(failures, 4)) if failures else interval
            await sleep(delay)
    emit(f'Watch complete: successful polls={successes}/{cycles}, logins={logins}. No images or mail.')
    return 0 if successes == cycles else 1
