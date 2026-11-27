"""Read-only cloud-to-SD matching for H4 still photos."""
import sqlite3
from contextlib import closing
from pathlib import Path


def queued_times(path, uid, begin, end):
    uri = Path(path).resolve().as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True)) as db:
        rows = db.execute('SELECT et_utc FROM events WHERE camera_uid=? '
                          'AND et_utc>=? AND et_utc<? ORDER BY et_utc',
                          (uid, begin, end)).fetchall()
    return [row[0] for row in rows]


def match_events(stamps, events, tolerance=2):
    """Only unique, mutually exclusive candidates; do not prefer exact matches."""
    photos = [e for e in events if e.event_type == 4 and e.length == 65535]
    candidates = [[i for i, e in enumerate(photos)
                   if abs(e.start_time - stamp) <= tolerance] for stamp in stamps]
    counts = {}
    for choices in candidates:
        for i in choices:
            counts[i] = counts.get(i, 0) + 1
    results = []
    for stamp, choices in zip(stamps, candidates):
        if not choices:
            results.append((stamp, 'missing', None))
        elif len(choices) != 1 or counts[choices[0]] != 1:
            results.append((stamp, 'ambiguous', None))
        else:
            results.append((stamp, 'matched', photos[choices[0]].start_time))
    return results
