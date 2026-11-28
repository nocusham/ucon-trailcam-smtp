"""Ucon account-scoped REST API, shared by intake and diagnostic tools."""
from uuid import uuid4

import httpx
from ucon_trailcam_smtp.sdk_credentials import HOST, USER_AGENT, encode_password
from ucon_trailcam_smtp.safe_diagnostics import error_kind
from ucon_trailcam_smtp.camera_selection import SelectionError, select_device, relay_credentials


class ApiError(Exception):
    """Contains only a fixed stage label and numeric status, never raw responses."""

    def __init__(self, message, *, stage=None, api_code=None, http_status=None, diagnostic_kind=None):
        super().__init__(message)
        self.stage, self.api_code, self.http_status = stage, api_code, http_status
        self.diagnostic_kind = diagnostic_kind


async def post_json(client, path, headers, body, stage):
    try:
        response = await client.post(HOST + path, headers=headers, json=body)
    except httpx.HTTPError as exc:
        raise ApiError(f'{stage}: transport failure ({error_kind(exc)})', stage=stage,
                       diagnostic_kind=error_kind(exc)) from None
    if response.status_code != 200:
        raise ApiError(f'{stage}: HTTP {response.status_code}', stage=stage, http_status=response.status_code)
    try:
        payload = response.json()
    except ValueError:
        raise ApiError(f'{stage}: invalid JSON', stage=stage, diagnostic_kind='invalid_json') from None
    if not isinstance(payload, dict):
        raise ApiError(f'{stage}: unexpected response shape', stage=stage, diagnostic_kind='invalid_schema')
    if payload.get('code') != 0:
        code = payload.get('code')
        code = code if type(code) is int else 'unavailable'
        raise ApiError(f'{stage}: API code {code}', stage=stage, api_code=code if type(code) is int else None,
                       diagnostic_kind='api_code' if type(code) is int else 'invalid_schema')
    data = payload.get('data')
    if not isinstance(data, dict):
        raise ApiError(f'{stage}: missing data object', stage=stage, diagnostic_kind='invalid_schema')
    return data


async def discover_devices(client, account, password):
    # Match the pinned SDK's Ucon login, host and account discovery.
    app_uuid = str(uuid4())
    headers = {
        'Content-Type': 'application/json; charset=utf-8',
        'User-Agent': USER_AGENT,
        'X-Ubiaapi-Callcontext': f'source=app&app=ucon&ver=2.0.10&uuid={app_uuid}&lang=en',
    }
    login = await post_json(client, '/api/v3/login', headers, {
        'account': account, 'password': encode_password(password),
        'app': 'ucon', 'app_version': '2.0.10', 'device_type': 1,
        'lang': 'en', 'brand': 'Linux',
    }, 'login')
    token = login.get('Token') or login.get('token')
    if not isinstance(token, str) or not token:
        raise ApiError('login: missing token', stage='login', diagnostic_kind='invalid_schema')
    headers = {**headers, 'X-Ubia-Auth-Usertoken': token,
               'X-Ubiaapi-Callcontext': (
                   f"source=app&app=ucon&ver=2.0.10&uuid={login.get('uuid', app_uuid)}&lang=en")}
    return headers, await list_devices(client, headers)


async def list_devices(client, headers):
    return (await post_json(client, '/api/v2/user/device_list', headers, {},
                            'device discovery')).get('infos')


async def authenticate(client, account, password, index, *, camera_uid=None):
    headers, devices = await discover_devices(client, account, password)
    try:
        device = select_device(devices, index, uid=camera_uid)
    except SelectionError as exc:
        raise ApiError(str(exc)) from None
    return headers, device['device_uid']


async def get_device_by_uid(account, password, uid):
    """Use one authenticated device-list response for UID and relay password."""
    from ucon_trailcam_smtp.sdk_credentials import DeviceCredentials
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        _, devices = await discover_devices(client, account, password)
    return DeviceCredentials(*relay_credentials(select_device(devices, uid=uid)))


async def list_cloud_events(client, headers, uid, begin, end):
    result = await post_json(client, '/api/user/qry/cloudvideo/list/v2', headers,
                             {'device_uids': [uid], 'begin': begin, 'end': end},
                             'cloud event list')
    items = result.get('items')
    if not isinstance(items, list):
        raise ApiError('cloud event list: missing items array', stage='cloud event list', diagnostic_kind='invalid_schema')
    return result
