"""One-shot, experimental account-scoped event query; no P4P connection."""
import argparse
import asyncio
import datetime as dt
from importlib.metadata import version
from urllib.parse import urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
from p4p_camera_sdk.credentials import HOST, USER_AGENT, encode_password
from ucon_auth import read_credentials


class ApiError(Exception):
    """Contains only a fixed stage label and numeric status, never raw responses."""


async def post_json(client, path, headers, body, stage):
    try:
        response = await client.post(HOST + path, headers=headers, json=body)
    except httpx.HTTPError as exc:
        raise ApiError(f'{stage}: transport failure ({type(exc).__name__})') from None
    if response.status_code != 200:
        raise ApiError(f'{stage}: HTTP {response.status_code}')
    try:
        payload = response.json()
    except ValueError:
        raise ApiError(f'{stage}: invalid JSON') from None
    if not isinstance(payload, dict):
        raise ApiError(f'{stage}: unexpected response shape')
    if payload.get('code') != 0:
        code = payload.get('code')
        code = code if type(code) is int else 'unavailable'
        raise ApiError(f'{stage}: API code {code}')
    data = payload.get('data')
    if not isinstance(data, dict):
        raise ApiError(f'{stage}: missing data object')
    return data


async def query_events(client, account, password, index, begin, end):
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
        raise ApiError('login: missing token')
    headers = {**headers, 'X-Ubia-Auth-Usertoken': token,
               'X-Ubiaapi-Callcontext': (
                   f"source=app&app=ucon&ver=2.0.10&uuid={login.get('uuid', app_uuid)}&lang=en")}
    devices = (await post_json(client, '/api/v2/user/device_list', headers, {},
                               'device discovery')).get('infos')
    if not isinstance(devices, list) or not 0 <= index < len(devices):
        raise ApiError('device discovery: index unavailable')
    device = devices[index]
    uid = device.get('device_uid') if isinstance(device, dict) else None
    if not isinstance(uid, str) or not uid:
        raise ApiError('device discovery: missing selected device identifier')
    result = await post_json(client, '/api/user/qry/cloudvideo/list/v2', headers,
                             {'device_uids': [uid], 'begin': begin, 'end': end},
                             'cloud event list')
    items = result.get('items')
    if not isinstance(items, list):
        raise ApiError('cloud event list: missing items array')
    return summarize(items, uid)


def summarize(items, uid):
    """Report only matching-device counts and safe event metadata."""
    rows = []
    unverified = 0
    for item in items:
        if not isinstance(item, dict) or item.get('uid', item.get('device_uid')) != uid:
            unverified += 1
            continue
        stamp = item.get('et_utc')
        if type(stamp) is not int or not 0 <= stamp <= 4102444800:
            stamp = None
        image = item.get('img_url')
        try:
            has_image = isinstance(image, str) and urlsplit(image).scheme == 'https' and bool(urlsplit(image).hostname)
        except ValueError:
            has_image = False
        rows.append((stamp, has_image))
    return rows, unverified


async def run(args, account, password, begin, end):
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        return await query_events(client, account, password, args.index, begin, end)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', type=int, default=0)
    window = parser.add_mutually_exclusive_group()
    window.add_argument('--day', type=dt.date.fromisoformat)
    window.add_argument('--hours', type=int, default=24)
    parser.add_argument('--tz', default='Europe/Berlin')
    args = parser.parse_args()
    if args.index < 0 or not 1 <= args.hours <= 168:
        parser.error('index must be nonnegative; hours must be 1–168')
    if version('p4p-camera-sdk') != '0.1.16':
        parser.error('Use the pinned SDK version 0.1.16')
    end = int(dt.datetime.now(dt.timezone.utc).timestamp())
    begin = end - args.hours * 3600
    if args.day:
        try:
            tz = ZoneInfo(args.tz)
        except Exception:
            parser.error('Invalid time zone')
        begin = int(dt.datetime.combine(args.day, dt.time.min, tzinfo=tz).timestamp())
        end = int(dt.datetime.combine(args.day + dt.timedelta(days=1), dt.time.min, tzinfo=tz).timestamp())
    try:
        account, password = read_credentials()
        print('Experimental cloud event query; no P4P/UDP camera session.')
        rows, unverified = asyncio.run(run(args, account, password, begin, end))
    except ApiError as exc:
        print(str(exc))
        return 1
    except Exception as exc:
        print(f'Cloud probe failed: {type(exc).__name__}. Details suppressed.')
        return 1
    print(f'Matching-device events: {len(rows)}; HTTPS image references: {sum(has for _, has in rows)}')
    print(f'Unverified/unmatched items ignored: {unverified}')
    for stamp, has_image in sorted(rows, key=lambda row: row[0] if row[0] is not None else -1):
        when = dt.datetime.fromtimestamp(stamp, dt.timezone.utc).isoformat() if stamp is not None else 'unknown'
        print(f'{when} | image reference: {"yes" if has_image else "no"}')
    print('No image URL, token, device ID or raw API response printed. No image downloaded.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
