"""Select due originals in bounded SD windows, independent of calendar days."""
from ucon_trailcam_smtp.download_retry import due_ids
from ucon_trailcam_smtp.media_retention import capture_cutoff


WINDOW_SECONDS = 3600


def plan_download(db, uid, now, limit, *, automatic_days=90):
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
