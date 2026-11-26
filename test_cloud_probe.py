import unittest
import httpx
from cloud_probe import query_events, summarize, ApiError


class CloudProbeTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_selected_device_requested(self):
        calls = []
        def respond(request):
            import json
            path = request.url.path
            calls.append(path)
            if path == '/api/v3/login':
                return httpx.Response(200, json={'code': 0, 'data': {'Token': 'synthetic'}})
            if path == '/api/v2/user/device_list':
                return httpx.Response(200, json={'code': 0, 'data': {'infos': [
                    {'device_uid': 'device-a'}, {'device_uid': 'device-b'}]}})
            self.assertEqual(path, '/api/user/qry/cloudvideo/list/v2')
            self.assertEqual(json.loads(request.content), {'device_uids': ['device-b'], 'begin': 1, 'end': 2})
            self.assertEqual(request.headers['X-Ubia-Auth-Usertoken'], 'synthetic')
            return httpx.Response(200, json={'code': 0, 'data': {'items': [
                {'uid': 'device-b', 'et_utc': 2, 'img_url': 'https://example.invalid/private'},
                {'uid': 'device-a', 'et_utc': 2}, {'et_utc': 2}]}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            self.assertEqual(await query_events(client, 'test@example.invalid', 'secret', 1, 1, 2),
                             ([(2, True)], 2))
        self.assertEqual(len(calls), 3)

    async def test_http_error_does_not_expose_body(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda _: httpx.Response(403, text='private token'))) as client:
            with self.assertRaisesRegex(ApiError, '^login: HTTP 403$'):
                await query_events(client, 'test@example.invalid', 'secret', 0, 1, 2)

    def test_invalid_fields_and_other_devices(self):
        rows, ignored = summarize([{'uid': 'own', 'et_utc': 'bad', 'img_url': 'file:///tmp/a'},
                                   {'uid': 'other', 'et_utc': 1},
                                   {'uid': 'own', 'et_utc': 2, 'img_url': 'https://['}], 'own')
        self.assertEqual(rows, [(None, False), (2, False)])
        self.assertEqual(ignored, 1)
