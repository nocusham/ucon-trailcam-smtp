"""One-shot, read-only Ucon compatibility probe for your own camera."""
import argparse
import asyncio
import contextlib
import datetime as dt
import getpass
import io
import logging
import time

from p4p_camera_sdk.credentials import CredentialClient
from p4p_camera_sdk.relay import RelaySession
from p4p_camera_sdk.sdcard_client import SdCardClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', type=int, default=0)
    parser.add_argument('--events', action='store_true', help='Explicitly request SD events (may wake camera)')
    parser.add_argument('--hours', type=int, default=24)
    args = parser.parse_args()
    if args.index < 0 or not 1 <= args.hours <= 168:
        parser.error('index must be nonnegative; hours must be 1–168')
    account = input('Ucon account: ').strip()
    password = getpass.getpass('Ucon password: ')
    if not account or not password:
        parser.error('Account and password are required')
    logging.disable(logging.CRITICAL)
    stage = 'account login / device discovery'
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            device = asyncio.run(CredentialClient(account, password).get_device(index=args.index))
        print('Account login and device discovery successful.')
        if not args.events:
            return 0
        stage = 'camera relay session / SD event listing'
        end = int(time.time())
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with RelaySession(device.device_uid, device.device_password) as session:
                events = SdCardClient(session).list_events(end - args.hours * 3600, end)
        print(f'Events returned: {len(events)}')
        for event in sorted(events, key=lambda e: e.start_time):
            stamp = dt.datetime.fromtimestamp(event.start_time, dt.timezone.utc).isoformat()
            print(f'{stamp} UTC | type={event.event_type} | length={event.length}')
        return 0
    except Exception as exc:
        print(f'Failed during {stage}: {type(exc).__name__}. Raw diagnostic details suppressed.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
