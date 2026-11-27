import unittest
import httpx
from cloud_probe import query_events, summarize, ApiError, describe_fields, print_event_schema
from contextlib import redirect_stdout
from io import StringIO


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

    async def test_transport_failure_has_safe_category(self):
        from safe_diagnostics import cloud_fields
        def respond(request):
            raise httpx.ReadTimeout('private URL?token=secret', request=request)
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with self.assertRaises(ApiError) as caught:
                await query_events(client, 'test@example.invalid', 'secret', 0, 1, 2)
        self.assertEqual(cloud_fields(caught.exception), 'stage=login category=read_timeout')
        self.assertNotIn('secret', str(caught.exception))

    async def test_invalid_json_has_safe_category(self):
        from safe_diagnostics import cloud_fields
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda _: httpx.Response(200, text='private response'))) as client:
            with self.assertRaises(ApiError) as caught:
                await query_events(client, 'test@example.invalid', 'secret', 0, 1, 2)
        self.assertEqual(cloud_fields(caught.exception), 'stage=login category=invalid_json')
        self.assertNotIn('private', str(caught.exception))

    async def test_wrong_password_structured_error(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={'code': 20005, 'data': {'private': 'synthetic'}}))) as client:
            with self.assertRaisesRegex(ApiError, '^login: API code 20005$') as caught:
                await query_events(client, 'test@example.invalid', 'secret', 0, 1, 2)
        self.assertEqual(caught.exception.stage, 'login')
        self.assertEqual(caught.exception.api_code, 20005)
        self.assertNotIn('synthetic', str(caught.exception))

    def test_invalid_fields_and_other_devices(self):
        rows, ignored = summarize([{'uid': 'own', 'et_utc': 'bad', 'img_url': 'file:///tmp/a'},
                                   {'uid': 'other', 'et_utc': 1},
                                   {'uid': 'own', 'et_utc': 2, 'img_url': 'https://['}], 'own')
        self.assertEqual(rows, [(None, False), (2, False)])
        self.assertEqual(ignored, 1)

    def test_schema_describes_values_without_disclosing_them(self):
        fields = dict(describe_fields({'img_url': 'http://example.invalid/private?token=secret',
                                       'snap': 'bucket/private.jpg',
                                       'empty': '', 'nested': {'url': 'https://example.invalid/x'},
                                       'itemid': 'secret-id', 'et_utc': 1795677006}))
        self.assertTrue(fields['img_url'].startswith('http URL'))
        self.assertTrue(fields['nested.url'].startswith('https URL'))
        self.assertIn('possible path', fields['snap'])
        self.assertEqual(fields['itemid'], 'string, length=9')
        self.assertEqual(fields['et_utc'], 'int')
        self.assertNotIn('secret', str(fields))
        self.assertNotIn('example.invalid', str(fields))

    def test_schema_skips_unmatched_records(self):
        out = StringIO()
        with redirect_stdout(out):
            print_event_schema({'items': [{'uid': 'own', 'image': ''},
                                         {'uid': 'other', 'private_field': 'secret'}]}, 'own')
        self.assertIn('item.image: empty string', out.getvalue())
        self.assertNotIn('private_field', out.getvalue())
