"""Select due originals in bounded SD windows, independent of calendar days."""
from ucon_trailcam_smtp.download_retry import due_ids
from ucon_trailcam_smtp.media_retention import capture_cutoff


WINDOW_SECONDS = 3600
DEFAULT_BATCH_LIMIT = 3
MAX_BATCH_LIMIT = 100  # Experimental software limit, not a camera capability.


def validate_batch_limit(value):
    if type(value) is not int or not 1 <= value <= MAX_BATCH_LIMIT:
        raise ValueError('Download batch limit must be an integer in 1–100')
    return value


def parse_batch_limit(raw, default=DEFAULT_BATCH_LIMIT):
    """Missing download section inherits the validated default."""
    validate_batch_limit(default)
    if raw is None:
        return default
    if not isinstance(raw, dict) or set(raw) - {'batch_limit'}:
        raise ValueError('Invalid download configuration')
    return validate_batch_limit(raw.get('batch_limit', default))


def effective_batch_limit(profile, override=None):
    return validate_batch_limit(profile.download_batch_limit if override is None else override)


def plan_download(db, uid, now, limit, *, automatic_days=90):
    validate_batch_limit(limit)
    cutoff = capture_cutoff(now, automatic_days)
    rows = db.execute("SELECT itemid,et_utc,state,metadata_json FROM events "
                      "WHERE camera_uid=? AND state='pending' AND et_utc>=? AND et_utc<=?",
                      (uid, cutoff, now)).fetchall()
    due = due_ids(db, uid, rows, cutoff, now + 1, now, limit)
    if not due:
        return None
    stamps = {r[0]: r[1] for r in rows}
    begin = stamps[due[0]]
    end = min(now + 1, begin + WINDOW_SECONDS)
    selected = [ident for ident in due if begin <= stamps[ident] < end]
    return begin, end, selected
