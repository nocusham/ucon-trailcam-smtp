"""One-shot, read-only Ucon compatibility probe for your own camera."""
import argparse
import asyncio
import contextlib
import datetime as dt
import getpass
import io
import logging
from collections import Counter
from importlib.metadata import version
import time

from p4p_camera_sdk.credentials import CredentialClient
from p4p_camera_sdk.relay import RelaySession
from p4p_camera_sdk.sdcard_client import SdCardClient


class DiagnosticRelay(RelaySession):
    """Collect only frame types, lengths and SD counters, never payloads."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.phase = 'initial'
        self.frames = Counter()
        self.headers = Counter()

    def send_ioctrl(self, channel, iotype, data):
        if iotype == 256:
            self.phase = 'SD query'
        return super().send_ioctrl(channel, iotype, data)

    def poll_ioctrl(self, timeout=5.0):
        for iotype, data in super().poll_ioctrl(timeout=timeout):
            self.frames[(self.phase, iotype)] += 1
            if iotype == 257:
                if len(data) < 12:
                    self.headers[('short header', len(data))] += 1
                else:
                    count = data[7]
                    total = int.from_bytes(data[8:10], 'little')
                    available = min(count, (len(data) - 12) // 8)
                    zero = sum(
                        int.from_bytes(data[16 + i * 8:18 + i * 8], 'little') == 0
                        for i in range(available)
                    )
                    self.headers[(count, total, available, zero)] += 1
            yield iotype, data

    def report(self):
        print('Decoded frame counts (no payloads):')
        if not self.frames:
            print('  None')
        for (phase, iotype), count in sorted(self.frames.items()):
            print(f'  {phase}: 0x{iotype:08x} ({iotype}) x {count}')
        for header, repeats in self.headers.items():
            if len(header) == 4:
                count, total, available, zero = header
                print(f'  SD header: count={count}, total={total}, available={available}, '
                      f'zero_length={zero}, repeats={repeats}')
            else:
                print(f'  SD response too short: {header[1]} bytes, repeats={repeats}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', type=int, default=0)
    parser.add_argument('--events', action='store_true', help='Explicitly request SD events (may wake camera)')
    parser.add_argument('--hours', type=int, default=24)
    args = parser.parse_args()
    if args.index < 0 or not 1 <= args.hours <= 168:
        parser.error('index must be nonnegative; hours must be 1–168')
    print(f'SDK version: {version("p4p-camera-sdk")}')
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
        session = DiagnosticRelay(device.device_uid, device.device_password)
        started = time.monotonic()
        print(f'Query UTC: {dt.datetime.fromtimestamp(end - args.hours * 3600, dt.timezone.utc).isoformat()}'
              f' to {dt.datetime.fromtimestamp(end, dt.timezone.utc).isoformat()}')
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                with session:
                    events = SdCardClient(session).list_events(end - args.hours * 3600, end)
        finally:
            print(f'Relay / SD query elapsed: {time.monotonic() - started:.1f} s')
            session.report()
        print(f'Events returned: {len(events)}')
        if not events:
            print('No events decoded; SD card may still contain recordings.')
        for event in sorted(events, key=lambda e: e.start_time):
            stamp = dt.datetime.fromtimestamp(event.start_time, dt.timezone.utc).isoformat()
            print(f'{stamp} UTC | type={event.event_type} | length={event.length}')
        return 0
    except Exception as exc:
        print(f'Failed during {stage}: {type(exc).__name__}. Raw diagnostic details suppressed.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
