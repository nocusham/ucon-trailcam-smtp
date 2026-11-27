"""Download public HTTP(S) image references and validate actual image content."""
import asyncio
import hashlib
import ipaddress
import re
import socket
import warnings
from io import BytesIO
from urllib.parse import urlsplit, urljoin

import httpx
from PIL import Image

MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 40_000_000
MAX_REDIRECTS = 3
FORMATS = {'JPEG': 'jpg', 'PNG': 'png', 'WEBP': 'webp', 'GIF': 'gif',
           'BMP': 'bmp', 'TIFF': 'tiff'}


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


def checked_url(value):
    if reference_scheme(value) is None:
        raise ImageError('Cloud image: missing HTTP(S) reference')
    try:
        parts = urlsplit(value)
        url = httpx.URL(value)
        if (parts.username is not None or parts.password is not None
                or parts.fragment or parts.port == 0 or '%' in parts.hostname
                or any(ord(c) < 33 or ord(c) == 127 for c in value)):
            raise ValueError
        return url
    except (ValueError, httpx.InvalidURL):
        raise ImageError('Cloud image: invalid URL format') from None


def public_address(host, port):
    """Resolve once; reject nonpublic answers and return a numeric address."""
    try:
        answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        addresses = [ipaddress.ip_address(a[4][0]) for a in answers]
    except (OSError, ValueError):
        raise ImageError('Cloud image: DNS resolution failed') from None
    if not addresses:
        raise ImageError('Cloud image: no DNS address')
    for ip in addresses:
        address = getattr(ip, 'ipv4_mapped', None) or ip
        if (not address.is_global or address.is_multicast or address.is_reserved
                or address.is_loopback or address.is_link_local):
            raise ImageError('Cloud image: nonpublic network destination refused')
    return str(addresses[0])


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


def validate_image(data):
    """Verify structure and fully decode a bounded single-frame raster image."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as im:
                fmt, (width, height) = im.format, im.size
                if fmt not in FORMATS or width * height > MAX_PIXELS:
                    raise ImageError('Cloud image: unsupported format or pixel limit exceeded')
                if getattr(im, 'n_frames', 1) != 1:
                    raise ImageError('Cloud image: multi-frame image not supported')
                im.verify()
            with Image.open(BytesIO(data)) as im:
                im.load()
        return FORMATS[fmt], width, height
    except ImageError:
        raise
    except Exception:
        raise ImageError('Cloud image: invalid or incomplete image') from None


async def fetch_image(client, item, output_dir):
    url = checked_url(item.get('img_url'))
    try:
        for hop in range(MAX_REDIRECTS + 1):
            port = url.port or (443 if url.scheme == 'https' else 80)
            host = url.raw_host.decode('ascii')
            ip = await asyncio.to_thread(public_address, host, port)
            # Pin the validated address; retain HTTP Host and TLS SNI/cert name.
            target = url.copy_with(host=ip)
            authority = f'[{host}]' if ':' in host else host
            if url.port is not None:
                authority += f':{url.port}'
            if url.scheme == 'http':
                print('Cloud image warning: API supplied an unencrypted HTTP URL.')
            client.cookies.clear()
            async with client.stream('GET', target, follow_redirects=False,
                                     headers={'Host': authority, 'Accept-Encoding': 'identity',
                                              'Connection': 'close'},
                                     extensions={'sni_hostname': host}) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get('location')
                    if not location or hop == MAX_REDIRECTS:
                        raise ImageError('Cloud image: redirect limit or missing target')
                    next_url = checked_url(urljoin(str(url), location))
                    if url.scheme == 'https' and next_url.scheme != 'https':
                        raise ImageError('Cloud image: HTTPS downgrade refused')
                    url = next_url
                    continue
                if response.status_code != 200:
                    raise ImageError(f'Cloud image: HTTP {response.status_code}')
                data = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    if len(data) + len(chunk) > MAX_IMAGE_BYTES:
                        raise ImageError('Cloud image: size limit exceeded')
                    data.extend(chunk)
                break
    except httpx.HTTPError as exc:
        raise ImageError(f'Cloud image: transport failure ({type(exc).__name__})') from None
    ext, width, height = validate_image(data)
    output_dir.mkdir(parents=True, exist_ok=True)
    dest = output_dir / f"cloud_{item['et_utc']}.{ext}"
    try:
        with dest.open('xb') as out:
            out.write(data)
    except FileExistsError:
        raise ImageError('Cloud image: local file already exists') from None
    return dest, len(data), hashlib.sha256(data).hexdigest(), width, height
