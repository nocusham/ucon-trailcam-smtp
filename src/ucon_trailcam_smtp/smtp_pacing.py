"""Shared persisted minimum interval between image and alarm SMTP attempts."""
import time

DEFAULT_INTERVAL = 30
MAX_INTERVAL = 3600
NANOSECONDS = 1_000_000_000


def validate_interval(value):
    if type(value) is not int or not 1 <= value <= MAX_INTERVAL:
        raise ValueError('SMTP interval must be an integer in 1–3600 seconds')
    return value


def parse_interval(raw):
    if raw is None:
        return DEFAULT_INTERVAL
    if not isinstance(raw, dict) or set(raw) - {'interval_seconds'}:
        raise ValueError('Invalid SMTP pacing configuration')
    return validate_interval(raw.get('interval_seconds', DEFAULT_INTERVAL))


class Pacer:
    """Use the same queue lock as delivery; reserve before network I/O."""
    def __init__(self, db, interval=DEFAULT_INTERVAL, *, clock=None):
        self.db = db
        self.interval = validate_interval(interval) * NANOSECONDS
        self.clock = time.time_ns if clock is None else clock

    def due(self):
        if not self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='smtp_pacing'").fetchone():
            return True
        row = self.db.execute('SELECT last_attempt_ns FROM smtp_pacing WHERE id=1').fetchone()
        return row is None or self.clock() - row[0] >= self.interval

    def reserve(self):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            self.db.execute('''CREATE TABLE IF NOT EXISTS smtp_pacing (
                id INTEGER PRIMARY KEY CHECK(id=1), last_attempt_ns INTEGER NOT NULL)''')
            now = self.clock()
            row = self.db.execute('SELECT last_attempt_ns FROM smtp_pacing WHERE id=1').fetchone()
            if row is not None and now - row[0] < self.interval:
                return False
            self.db.execute('INSERT OR REPLACE INTO smtp_pacing VALUES (1,?)', (now,))
            return True
