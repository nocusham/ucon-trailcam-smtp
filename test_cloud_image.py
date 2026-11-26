import tempfile
import unittest
from pathlib import Path

import httpx
from cloud_image import ImageError, SNAPSHOT_HOST, secure_image_url, select_latest, fetch_image


class CloudImageTests(unittest.IsolatedAsyncioTestCase):
    def test_upgrade_preserves_signed_query(self):
        original = f'http://{SNAPSHOT_HOST}/a%2Fb.jpg?sig=a%2B%2F&x=1'
        self.assertEqual(secure_image_url(original), 'https' + original[4:])
        for bad in ['http://localhost/a', f'http://{SNAPSHOT_HOST}.example.invalid/a',
                    f'http://user@{SNAPSHOT_HOST}/a', f'http://{SNAPSHOT_HOST}:81/a']:
            with self.assertRaises(ImageError):
                secure_image_url(bad)

    def test_select_own_latest(self):
        items = [{'uid': 'own', 'et_utc': 1}, {'uid': 'other', 'et_utc': 3},
                 {'uid': 'own', 'et_utc': 2}]
        self.assertEqual(select_latest(items, 'own'), items[2])
        with self.assertRaises(ImageError):
            select_latest(items + [items[2]], 'own')

    async def test_https_download_and_no_overwrite(self):
        item = {'et_utc': 2, 'img_url': f'http://{SNAPSHOT_HOST}/a?sig=a%2B'}
        payload = bytes.fromhex('ffd8ffe00002ffd9')  # synthetic boundary fixture
        def respond(request):
            self.assertEqual(request.url.scheme, 'https')
            self.assertEqual(request.url.query, b'sig=a%2B')
            self.assertNotIn('Authorization', request.headers)
            self.assertNotIn('X-Ubia-Auth-Usertoken', request.headers)
            return httpx.Response(200, content=payload)
        with tempfile.TemporaryDirectory() as tmp:
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
                dest, size, _ = await fetch_image(client, item, Path(tmp))
                self.assertEqual(dest.read_bytes(), payload)
                self.assertEqual(size, len(payload))
                with self.assertRaises(ImageError):
                    await fetch_image(client, item, Path(tmp))

    async def test_reject_redirect_and_non_jpeg(self):
        item = {'et_utc': 2, 'img_url': f'http://{SNAPSHOT_HOST}/a'}
        with tempfile.TemporaryDirectory() as tmp:
            for response in [httpx.Response(302, headers={'Location': 'http://example.invalid'}),
                             httpx.Response(200, content=b'error')]:
                async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response)) as client:
                    with self.assertRaises(ImageError):
                        await fetch_image(client, item, Path(tmp))
            self.assertEqual(list(Path(tmp).iterdir()), [])
