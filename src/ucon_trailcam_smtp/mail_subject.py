"""Readable configured-camera subjects using capture time, not delivery time."""
import datetime as dt
import re
from zoneinfo import ZoneInfo


def capture_time(stamp):
    local = dt.datetime.fromtimestamp(stamp, dt.timezone.utc).astimezone(ZoneInfo('Europe/Berlin'))
    label = 'MESZ' if local.dst() else 'MEZ'
    return f'{local:%d.%m.%Y %H:%M:%S} {label}'


def camera_subject(name, stamps, *, grouped=False):
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', name):
        raise ValueError('Invalid configured camera name')
    stamps = sorted(stamps)
    if not stamps or (not grouped and len(stamps) != 1):
        raise ValueError('Invalid subject capture times')
    when = capture_time(stamps[0])
    if grouped:
        count = len(stamps)
        if stamps[-1] != stamps[0]:
            when += ' bis ' + capture_time(stamps[-1])
        kind = 'Originalbild' if count == 1 else 'Originalbilder'
        return f'UCON {name} - {count} {kind} - {when}'
    return f'UCON {name} - {when}'
