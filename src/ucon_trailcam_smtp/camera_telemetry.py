"""Allowlisted passive cloud telemetry and optional inactivity observations."""
from ucon_trailcam_smtp.health_alerts import init_health, observe

REFRESH_SECONDS = 900
FRESH_SECONDS = 1800
MAX_FALLBACK_GAP = 3600


def init_telemetry(db):
    init_health(db)
    with db:
        db.execute('''CREATE TABLE IF NOT EXISTS camera_telemetry (
            camera_uid TEXT PRIMARY KEY, observed_utc INTEGER NOT NULL,
            latest_active_utc INTEGER, activity_field_seen INTEGER NOT NULL,
            battery INTEGER, signal INTEGER, online_state TEXT,
            charging INTEGER, low_power INTEGER, fallback_since INTEGER,
            source TEXT NOT NULL, activity_utc INTEGER, status TEXT NOT NULL)''')


def integer(value, low, high):
    return value if type(value) is int and low <= value <= high else None


def flag(value):
    return int(value) if type(value) is bool else None


def record_snapshot(db, uid, device, now, *, enabled=False, days=7,
                    photo_utc=None, coverage_end=None):
    """Fresh successful device response only; never persist raw API values.

    Photo fallback starts at first observed complete intake interval and resets
    after a monitoring gap. Missing/invalid activity on a known capable model
    is unknown, not an invitation to switch sources.
    """
    if (device.get('device_uid') != uid or type(now) is not int or now <= 0
            or type(enabled) is not bool or type(days) is not int or not 1 <= days <= 365):
        raise ValueError('Invalid telemetry observation')
    previous = db.execute('SELECT observed_utc,latest_active_utc,activity_field_seen,fallback_since '
                          'FROM camera_telemetry WHERE camera_uid=?', (uid,)).fetchone()
    if previous is not None and now <= previous[0]:
        return 'unchanged'
    info = device.get('dynamic_info')
    valid_info = isinstance(info, dict) and info.get('device_uid', uid) == uid
    info = info if valid_info else {}
    seen = bool(previous and previous[2]) or 'latest_active_utc' in info
    old_active = previous[1] if previous else None
    stamp = integer(info.get('latest_active_utc'), 1, min(now, 4102444800))
    source, activity, fallback = 'unknown', None, None
    observed_photo = None
    if valid_info and stamp is not None and (old_active is None or stamp >= old_active):
        source, activity, old_active = 'cloud_activity', stamp, stamp
    elif valid_info and not seen and coverage_end == now:
        continuous = (previous is not None and previous[3] is not None
                      and now - previous[0] <= MAX_FALLBACK_GAP)
        fallback = previous[3] if continuous else now
        observed_photo = integer(photo_utc, fallback, now)
        source, activity = 'photo_events', max(fallback, observed_photo or fallback)
    status = ('disabled' if not enabled else 'unknown' if activity is None else
              'inactive' if now - activity >= days * 86400 else 'active')
    if status == 'active' and source == 'photo_events' and observed_photo is None:
        # A new monitoring baseline is not evidence that the camera recovered.
        status = 'watching'
    online = info.get('online_state')
    online = online if isinstance(online, str) and len(online) <= 3 and online.isascii() and online.isdigit() else None
    with db:
        db.execute('''INSERT OR REPLACE INTO camera_telemetry VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                   (uid, now, old_active, int(seen), integer(info.get('battery'), 0, 100),
                    integer(info.get('signal'), 0, 255), online, flag(info.get('is_battery_charging')),
                    flag(info.get('is_low_power')), fallback, source, activity, status))
    if status not in ('active', 'inactive') or (previous and now - previous[0] > MAX_FALLBACK_GAP):
        # Discard an unannounced candidate after an observation gap; keep an
        # announced incident until actual recovery evidence is available.
        with db:
            db.execute("DELETE FROM health_incidents WHERE category='inactivity' AND scope=? AND last_notice IS NULL", (uid,))
    if status in ('active', 'inactive'):
        observe(db, 'inactivity', uid, healthy=status == 'active', now=now)
    return status


def fresh_scopes(db, enabled_uids, now):
    """Only pass this set to alarm dispatch after a successful cloud check."""
    return {uid for uid, observed, status in db.execute(
        'SELECT camera_uid,observed_utc,status FROM camera_telemetry')
            if uid in enabled_uids and 0 <= now - observed <= FRESH_SECONDS
            and status in ('active', 'inactive')}
