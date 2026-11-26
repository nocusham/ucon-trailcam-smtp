"""Bounded, HTTPS-only test download from the observed Ucon snapshot host."""
import hashlib
from urllib.parse import urlsplit, urlunsplit

import httpx

SNAPSHOT_HOST = 'ubiasnap-eu-uk.oss-eu-west-1.aliyuncs.com'
MAX_IMAGE_BYTES = 8 * 1024 * 1024


class ImageError(Exception):
    """Fixed diagnostic text only; never include signed URLs."""


def reference_scheme(value):
    if not isinstance(value, str):
        return None
    try:
        parts = urlsplit(value)
        if parts.scheme in ('http', 'https') and parts.hostname:
            return parts.scheme
    except ValueError:
        pass
    return None


def secure_image_url(value):
    if reference_scheme(value) is None:
        raise ImageError('Cloud image: missing HTTP(S) reference')
    try:
        parts = urlsplit(value)
        if (parts.hostname != SNAPSHOT_HOST or parts.username is not None
                or parts.password is not None or parts.fragment
                or parts.port not in (None, 80 if parts.scheme == 'http' else 443)):
            raise ImageError('Cloud image: unverified storage host or URL format')
    except ValueError:
        raise ImageError('Cloud image: invalid URL format') from None
    return urlunsplit(('https', SNAPSHOT_HOST, parts.path, parts.query, ''))


def select_latest(items, uid):
    own = [item for item in items if isinstance(item, dict)
           and item.get('uid', item.get('device_uid')) == uid
           and type(item.get('et_utc')) is int
           and 0 <= item['et_utc'] <= 4102444800]
    if not own:
        raise ImageError('Cloud image: no matching event')
    latest = max(item['et_utc'] for item in own)
    candidates = [item for item in own if item['et_utc'] == latest]
    if len(candidates) != 1:
        raise ImageError('Cloud image: latest event ambiguous')
    return candidates[0]


async def fetch_image(client, item, output_dir):
    url = secure_image_url(item.get('img_url'))
    try:
        async with client.stream('GET', url, follow_redirects=False,
                                 headers={'Accept-Encoding': 'identity'}) as response:
            if response.status_code != 200:
                raise ImageError(f'Cloud image: HTTP {response.status_code}')
            data = bytearray()
            async for chunk in response.aiter_bytes(chunk_size=65536):
                if len(data) + len(chunk) > MAX_IMAGE_BYTES:
                    raise ImageError('Cloud image: size limit exceeded')
                data.extend(chunk)
    except httpx.HTTPError as exc:
        raise ImageError(f'Cloud image: transport failure ({type(exc).__name__})') from None
    if len(data) < 4 or not data.startswith(b'\xff\xd8') or not data.endswith(b'\xff\xd9'):
        raise ImageError('Cloud image: JPEG boundary check failed')
    output_dir.mkdir(parents=True, exist_ok=True)
    dest = output_dir / f"cloud_{item['et_utc']}.jpg"
    try:
        with dest.open('xb') as out:
            out.write(data)
    except FileExistsError:
        raise ImageError('Cloud image: local file already exists') from None
    return dest, len(data), hashlib.sha256(data).hexdigest()
