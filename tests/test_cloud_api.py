import json
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from ucon_trailcam_smtp.cloud_api import ApiError, authenticate, discover_devices, get_device_by_uid, list_cloud_events, list_devices
from ucon_trailcam_smtp.safe_diagnostics import cloud_fields


class CloudApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_login_refresh_and_event_query_reuse_session(self):
        calls = []
        devices = [{'device_uid': 'synthetic-a'}, {'device_uid': 'synthetic-b'}]

        def respond(request):
            calls.append(request.url.path)
            self.assertEqual(request.method, 'POST')
            self.assertEqual(request.headers['Content-Type'], 'application/json; charset=utf-8')
            body = json.loads(request.content)
            if request.url.path == '/api/v3/login':
                self.assertNotIn('X-Ubia-Auth-Usertoken', request.headers)
                self.assertEqual(body, {'account': 'test@example.invalid', 'password': 'encoded-fixture',
                                        'app': 'ucon', 'app_version': '2.0.10', 'device_type': 1,
                                        'lang': 'en', 'brand': 'Linux'})
                self.assertIn('uuid=local-fixture&lang=en', request.headers['X-Ubiaapi-Callcontext'])
                return httpx.Response(200, json={'code': 0, 'data': {'Token': 'fixture-token', 'uuid': 'server-fixture'}})
            self.assertEqual(request.headers['X-Ubia-Auth-Usertoken'], 'fixture-token')
            self.assertEqual(request.headers['X-Ubiaapi-Callcontext'],
                             'source=app&app=ucon&ver=2.0.10&uuid=server-fixture&lang=en')
            if request.url.path == '/api/v2/user/device_list':
                self.assertEqual(body, {})
                return httpx.Response(200, json={'code': 0, 'data': {'infos': devices}})
            self.assertEqual(request.url.path, '/api/user/qry/cloudvideo/list/v2')
            self.assertEqual(body, {'device_uids': ['synthetic-b'], 'begin': 100, 'end': 200})
            return httpx.Response(200, json={'code': 0, 'data': {'items': [], 'next': 7}})

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with patch('ucon_trailcam_smtp.cloud_api.encode_password', return_value='encoded-fixture') as encode, \
                    patch('ucon_trailcam_smtp.cloud_api.uuid4', return_value='local-fixture'):
                headers, found = await discover_devices(client, 'test@example.invalid', 'fixture-password')
                self.assertEqual(found, devices)
                self.assertEqual(await list_devices(client, headers), devices)
                self.assertEqual(await list_cloud_events(client, headers, 'synthetic-b', 100, 200),
                                 {'items': [], 'next': 7})
            encode.assert_called_once_with('fixture-password')
        self.assertEqual(calls, ['/api/v3/login', '/api/v2/user/device_list',
                                 '/api/v2/user/device_list', '/api/user/qry/cloudvideo/list/v2'])

    async def test_login_rejection_stops_before_device_request(self):
        calls = []

        def respond(request):
            calls.append(request.url.path)
            return httpx.Response(200, json={'code': 20005, 'data': {'private': 'fixture-secret'}})

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with patch('ucon_trailcam_smtp.cloud_api.encode_password', return_value='encoded-fixture'):
                with self.assertRaises(ApiError) as caught:
                    await discover_devices(client, 'test@example.invalid', 'fixture-password')
        self.assertEqual(calls, ['/api/v3/login'])
        self.assertEqual(cloud_fields(caught.exception), 'stage=login category=api_code api_code=20005')
        self.assertNotIn('fixture-secret', str(caught.exception))

    async def test_missing_token_stops_before_device_request(self):
        calls = []

        def respond(request):
            calls.append(request.url.path)
            return httpx.Response(200, json={'code': 0, 'data': {'other': 'fixture-secret'}})

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with patch('ucon_trailcam_smtp.cloud_api.encode_password', return_value='encoded-fixture'):
                with self.assertRaises(ApiError) as caught:
                    await discover_devices(client, 'test@example.invalid', 'fixture-password')
        self.assertEqual(calls, ['/api/v3/login'])
        self.assertEqual(cloud_fields(caught.exception), 'stage=login category=invalid_schema')

    async def test_invalid_event_array_is_not_an_empty_success(self):
        for data in ({}, {'items': None}, {'items': {'private': 'fixture-secret'}}):
            with self.subTest(data=data):
                async with httpx.AsyncClient(transport=httpx.MockTransport(
                        lambda _: httpx.Response(200, json={'code': 0, 'data': data}))) as client:
                    with self.assertRaises(ApiError) as caught:
                        await list_cloud_events(client, {}, 'synthetic-a', 100, 200)
                self.assertEqual(cloud_fields(caught.exception), 'stage=cloud_event_list category=invalid_schema')
                self.assertNotIn('fixture-secret', str(caught.exception))

    async def test_uid_selection_never_falls_back_to_index(self):
        a, b = {'device_uid': 'synthetic-a'}, {'device_uid': 'synthetic-b'}
        with patch('ucon_trailcam_smtp.cloud_api.discover_devices', new_callable=AsyncMock) as discover:
            discover.return_value = ({'fixture': 'header'}, [b, a])
            self.assertEqual(await authenticate(None, 'account', 'password', 0, camera_uid='synthetic-a'),
                             ({'fixture': 'header'}, 'synthetic-a'))
            for devices in ([b], [a, a], None):
                discover.return_value = ({}, devices)
                with self.assertRaises(ApiError):
                    await authenticate(None, 'account', 'password', 0, camera_uid='synthetic-a')

    async def test_relay_credentials_from_selected_device_only(self):
        a = {'device_uid': 'synthetic-a', 'device_pwd': 'fixture-a', 'device_name': 'a'}
        b = {'device_uid': 'synthetic-b', 'device_pwd': 'fixture-b', 'device_name': 'b'}
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: self.fail('unexpected request')))
        with patch('ucon_trailcam_smtp.cloud_api.httpx.AsyncClient', return_value=client) as factory, \
                patch('ucon_trailcam_smtp.cloud_api.discover_devices', new_callable=AsyncMock, return_value=({}, [b, a])) as discover, \
                patch('ucon_trailcam_smtp.sdk_credentials.DeviceCredentials') as credentials:
            self.assertIs(await get_device_by_uid('account', 'password', 'synthetic-a'), credentials.return_value)
            factory.assert_called_once_with(timeout=30, follow_redirects=False)
            discover.assert_awaited_once_with(client, 'account', 'password')
            credentials.assert_called_once_with('synthetic-a', 'fixture-a', 'a')
        self.assertTrue(client.is_closed)
