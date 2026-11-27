"""Retain only explicitly requested event fields, independently of image source."""
import json
import os

FIELDS = ('itemid', 'et_utc', 'battery', 'type', 'ai_result', 'user_tag')


def event_metadata(item):
    if not isinstance(item, dict):
        raise ValueError('Event metadata must be an object')
    return {key: item.get(key) for key in FIELDS}


def select_event(items, uid, timestamp):
    matches = [item for item in items if isinstance(item, dict)
               and item.get('uid', item.get('device_uid')) == uid
               and type(item.get('et_utc')) is int
               and item['et_utc'] == timestamp]
    if len(matches) != 1:
        raise ValueError('Cloud event timestamp missing or ambiguous')
    return matches[0]


def save_metadata(path, item):
    metadata = event_metadata(item)
    encoded = json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as out:
        out.write(encoded)


def load_metadata(path):
    with path.open(encoding='utf-8') as source:
        data = source.read(1_048_577)
    if len(data) > 1_048_576:
        raise ValueError('Event metadata exceeds size limit')
    return event_metadata(json.loads(data))


def metadata_text(item):
    metadata = event_metadata(item)
    return '\n'.join(f'{key}: {json.dumps(metadata[key], ensure_ascii=False, allow_nan=False)}'
                     for key in FIELDS)
