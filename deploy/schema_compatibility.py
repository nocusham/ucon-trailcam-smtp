"""Conservative version-1 schema contract for the reviewed reference runtime.

No runtime imports or migrations. Inspect only a verified standalone backup,
never the active queue. Literal DDL from the audited runtime at cff4b87,
with optional D2 pacing, R2c attempts and R3 history tables; no migration of existing
tables. Changes require explicit compatibility review.
"""
from contextlib import closing
from pathlib import Path
import sqlite3

from deploy.state_backup import BackupError, read_db, verify_backup


SCHEMA_VERSION = 1
REQUIRED = frozenset(('events', 'cloud_runtime', 'cloud_cursors',
                      'health_incidents', 'camera_telemetry', 'download_retries'))
DDL = {
    'camera_telemetry': """CREATE TABLE IF NOT EXISTS camera_telemetry (
            camera_uid TEXT PRIMARY KEY, observed_utc INTEGER NOT NULL,
            latest_active_utc INTEGER, activity_field_seen INTEGER NOT NULL,
            battery INTEGER, signal INTEGER, online_state TEXT,
            charging INTEGER, low_power INTEGER, fallback_since INTEGER,
            source TEXT NOT NULL, activity_utc INTEGER, status TEXT NOT NULL)""",
    'camera_telemetry_history': """CREATE TABLE IF NOT EXISTS camera_telemetry_history (
            camera_uid TEXT NOT NULL, observed_utc INTEGER NOT NULL,
            latest_active_utc INTEGER, battery INTEGER, signal INTEGER,
            online_state TEXT, charging INTEGER, low_power INTEGER,
            PRIMARY KEY(camera_uid,observed_utc))""",
    'cloud_cursors': """CREATE TABLE IF NOT EXISTS cloud_cursors (
            camera_uid TEXT PRIMARY KEY, start_utc INTEGER NOT NULL, last_end INTEGER NOT NULL)""",
    'cloud_runtime': """CREATE TABLE IF NOT EXISTS cloud_runtime (
            id INTEGER PRIMARY KEY CHECK(id=1), failures INTEGER NOT NULL, next_due INTEGER NOT NULL)""",
    'deliveries': """CREATE TABLE IF NOT EXISTS deliveries (
            camera_uid TEXT NOT NULL, itemid TEXT NOT NULL,
            message_id TEXT NOT NULL, started_utc INTEGER NOT NULL,
            accepted_utc INTEGER, PRIMARY KEY(camera_uid,itemid))""",
    'delivery_routes': """CREATE TABLE IF NOT EXISTS delivery_routes (
                camera_uid TEXT NOT NULL, itemid TEXT NOT NULL,
                route_json TEXT NOT NULL, PRIMARY KEY(camera_uid,itemid))""",
    'download_attempts': """CREATE TABLE IF NOT EXISTS download_attempts (
            path TEXT PRIMARY KEY, camera_uid TEXT NOT NULL, itemid TEXT NOT NULL,
            created_utc INTEGER NOT NULL)""",
    'download_retries': """CREATE TABLE IF NOT EXISTS download_retries (
            camera_uid TEXT NOT NULL, itemid TEXT NOT NULL,
            last_attempt INTEGER NOT NULL, next_due INTEGER NOT NULL,
            failures INTEGER NOT NULL DEFAULT 0, first_failure INTEGER,
            last_failure INTEGER, failed_attempt INTEGER, reason TEXT,
            PRIMARY KEY(camera_uid,itemid))""",
    'downloads': """CREATE TABLE IF NOT EXISTS downloads (
            camera_uid TEXT NOT NULL, itemid TEXT NOT NULL, sd_time INTEGER NOT NULL,
            path TEXT NOT NULL, sha256 TEXT NOT NULL, size INTEGER NOT NULL,
            width INTEGER NOT NULL, height INTEGER NOT NULL,
            PRIMARY KEY(camera_uid,itemid), UNIQUE(camera_uid,sd_time))""",
    'events': """CREATE TABLE IF NOT EXISTS events (
                camera_uid TEXT NOT NULL,
                itemid TEXT NOT NULL,
                et_utc INTEGER NOT NULL,
                metadata_json TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending',
                PRIMARY KEY (camera_uid, itemid)
            )""",
    'health_incidents': """CREATE TABLE IF NOT EXISTS health_incidents (
            category TEXT NOT NULL, scope TEXT NOT NULL, first_failure INTEGER NOT NULL,
            last_failure INTEGER NOT NULL, failures INTEGER NOT NULL, code INTEGER,
            blocked INTEGER NOT NULL, recovered_at INTEGER, last_attempt INTEGER,
            last_notice INTEGER, PRIMARY KEY(category,scope))""",
    'media_cleanup': """CREATE TABLE IF NOT EXISTS media_cleanup (
                camera_uid TEXT NOT NULL,itemid TEXT NOT NULL,removed_utc INTEGER NOT NULL,
                size INTEGER NOT NULL,PRIMARY KEY(camera_uid,itemid))""",
    'smtp_pacing': """CREATE TABLE IF NOT EXISTS smtp_pacing (
                id INTEGER PRIMARY KEY CHECK(id=1), last_attempt_ns INTEGER NOT NULL)""",
    'smtp_retries': """CREATE TABLE IF NOT EXISTS smtp_retries (
            camera_uid TEXT PRIMARY KEY, failures INTEGER NOT NULL,
            last_failure INTEGER NOT NULL, next_due INTEGER NOT NULL)""",
}


def schema_rows(db):
    return set(db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master'))


def expected_rows(tables):
    # Only execute the trusted literal definitions above, never SQL from
    # a backup or a candidate release.
    with closing(sqlite3.connect(':memory:')) as db:
        for name in sorted(tables):
            db.execute(DDL[name])
        return schema_rows(db)


def check_schema(db):
    """Read-only check of exact SQLite catalog, including autoindexes.

    All six startup tables are required. Eight lazily created tables are
    optional, but must have exactly the reviewed schema when present.
    This deliberately rejects even benign unreviewed schema differences.
    """
    if (db.execute('PRAGMA user_version').fetchone() != (0,)
            or db.execute('PRAGMA application_id').fetchone() != (0,)):
        raise BackupError('Unexpected SQLite schema version or application ID')
    rows = schema_rows(db)
    tables = {name for kind, name, _, _ in rows if kind == 'table'}
    if not REQUIRED <= tables or not tables <= DDL.keys():
        raise BackupError('Unexpected or missing queue tables')
    if rows != expected_rows(tables):
        raise BackupError('Queue schema differs from reviewed contract')
    return {'schema_contract': SCHEMA_VERSION, 'tables': len(tables)}


def check_backup_schema(backup):
    """Validate private backup integrity and compare the standalone schema."""
    backup = Path(backup).absolute()
    verify_backup(backup)
    with closing(read_db(backup / 'state/events.sqlite3')) as db:
        return check_schema(db)
