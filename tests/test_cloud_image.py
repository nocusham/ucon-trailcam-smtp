import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import httpx
from PIL import Image
from ucon_trailcam_smtp.cloud_image import ImageError, checked_url, public_address, select_latest, fetch_image, validate_image


def fixture(fmt='JPEG'):
    buffer = BytesIO()
    Image.new('RGB', (12, 8), 'green').save(buffer, format=fmt)
    return buffer.getvalue()


class CloudImageTests(unittest.IsolatedAsyncioTestCase):
    def test_accept_arbitrary_http_and_https_origins(self):
        for url in ('http://example.invalid/a%2Fb?sig=a%2B',
                    'https://new.example.invalid:8443/image'):
            self.assertEqual(str(checked_url(url)), url)
        for bad in ('file:///tmp/a', 'http://user:secret@example.invalid/a',
                    'https://example.invalid/a#private'):
            with self.assertRaises(ImageError):
                checked_url(bad)

    def test_public_dns_guard(self):
        for addr in ('127.0.0.1', '10.0.0.1', '169.254.169.254', '::1',
                     '::ffff:192.168.1.1', '224.0.0.1'):
            with patch('socket.getaddrinfo', return_value=[(0, 0, 0, '', (addr, 80))]):
                with self.assertRaises(ImageError):
                    public_address('test.invalid', 80)
        with patch('socket.getaddrinfo', return_value=[(0, 0, 0, '', ('8.8.8.8', 80))]):
            self.assertEqual(public_address('test.invalid', 80), '8.8.8.8')

    def test_select_own_latest(self):
        items = [{'uid': 'own', 'et_utc': 1}, {'uid': 'other', 'et_utc': 3},
                 {'uid': 'own', 'et_utc': 2}]
        self.assertEqual(select_latest(items, 'own'), items[2])
        with self.assertRaises(ImageError):
            select_latest(items + [items[2]], 'own')

    def test_actual_image_decode(self):
        self.assertEqual(validate_image(fixture()), ('jpg', 12, 8))
        self.assertEqual(validate_image(fixture('PNG')), ('png', 12, 8))
        for bad in (b'<html>error</html>', bytes.fromhex('ffd8ffe00002ffd9'), fixture()[:100]):
            with self.assertRaises(ImageError):
                validate_image(bad)
        with patch('ucon_trailcam_smtp.cloud_image.MAX_PIXELS', 10):
            with self.assertRaises(ImageError):
                validate_image(fixture())

    async def test_http_download_valid_content_and_no_overwrite(self):
        item = {'et_utc': 2, 'img_url': 'http://new.example.invalid/a?sig=a%2B'}
        payload = fixture('PNG')
        def respond(request):
            self.assertEqual(request.url.scheme, 'http')
            self.assertEqual(request.url.host, '8.8.8.8')
            self.assertEqual(request.headers['Host'], 'new.example.invalid')
            self.assertEqual(request.url.query, b'sig=a%2B')
            self.assertNotIn('Authorization', request.headers)
            self.assertNotIn('X-Ubia-Auth-Usertoken', request.headers)
            return httpx.Response(200, content=payload, headers={'Content-Type': 'application/octet-stream'})
        with tempfile.TemporaryDirectory() as tmp, patch('ucon_trailcam_smtp.cloud_image.public_address', return_value='8.8.8.8'):
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
                dest, size, _, w, h = await fetch_image(client, item, Path(tmp))
                self.assertEqual(dest.suffix, '.png')
                self.assertEqual(dest.read_bytes(), payload)
                self.assertEqual((size, w, h), (len(payload), 12, 8))
                with self.assertRaises(ImageError):
                    await fetch_image(client, item, Path(tmp))

    async def test_redirect_and_tls_identity(self):
        item = {'et_utc': 3, 'img_url': 'http://a.example.invalid/a'}
        def respond(request):
            if request.headers['Host'] == 'a.example.invalid':
                return httpx.Response(302, headers={'Location': 'https://b.example.invalid/b'})
            self.assertEqual(request.url.scheme, 'https')
            self.assertEqual(request.extensions['sni_hostname'], 'b.example.invalid')
            return httpx.Response(200, content=fixture())
        with tempfile.TemporaryDirectory() as tmp, patch('ucon_trailcam_smtp.cloud_image.public_address', return_value='8.8.8.8'):
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
                dest, *_ = await fetch_image(client, item, Path(tmp))
                self.assertEqual(dest.suffix, '.jpg')

    async def test_reject_fake_image_and_downgrade(self):
        item = {'et_utc': 2, 'img_url': 'https://example.invalid/a'}
        with tempfile.TemporaryDirectory() as tmp, patch('ucon_trailcam_smtp.cloud_image.public_address', return_value='8.8.8.8'):
            for response in (httpx.Response(302, headers={'Location': 'http://example.invalid/b'}),
                             httpx.Response(200, content=b'error', headers={'Content-Type': 'image/jpeg'})):
                async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response)) as client:
                    with self.assertRaises(ImageError):
                        await fetch_image(client, item, Path(tmp))
            self.assertEqual(list(Path(tmp).iterdir()), [])
