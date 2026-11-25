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
from unittest.mock import patch
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from h4_events import list_events_staged
from h4_transport import TransportTrace
from h4_download import native_frames, download_photo
from pathlib import Path
import time

from p4p_camera_sdk.credentials import CredentialClient
from p4p_camera_sdk.relay import RelaySession
import p4p_camera_sdk.relay as sdk_relay
from p4p_camera_sdk.p4p_crypto import encode
from h4_compat import recover_control
from p4p_camera_sdk.sdcard_client import SdCardClient
from p4p_camera_sdk.sdcard import (
    IOTYPE_GET_SD_STATUS_REQ, IOTYPE_GET_SD_STATUS_RSP, build_get_sd_status,
    IOTYPE_GET_ADVANCE_SETTINGS_REQ, IOTYPE_GET_ADVANCE_SETTINGS_RSP,
)


class DiagnosticRelay(RelaySession):
    """Collect only frame types, lengths and SD counters, never payloads."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.phase = 'initial'
        self.frames = Counter()
        self.headers = Counter()
        self.sent = Counter()
        self.lengths = Counter()
        self.last_frame = {}
        self.encoded_packets = 0
        self.recovered = Counter()
        self.transport = TransportTrace()
        self.relay_rx = Counter()
        self.relay_last = {}
        self.native_download = False

    def _drain_frames(self):
        if self.native_download:
            yield from native_frames(self)
            return
        frames = super()._drain_frames()
        while True:
            before = bytes(self._app_buf)
            try:
                kind, data = next(frames)
            except StopIteration:
                return
            new_kind, body = recover_control(before, len(self._app_buf), kind, data)
            if new_kind != kind:
                self.recovered[new_kind] += 1
            yield new_kind, body

    def send_ioctrl(self, channel, iotype, data):
        # 0.1.14 sends directly; 0.1.16 delegates to send_ioctrl_batch.
        if iotype == 256:
            self.phase = 'SD query'
        if not hasattr(RelaySession, 'send_ioctrl_batch'):
            self.sent[(self.phase, iotype)] += 1
        return super().send_ioctrl(channel, iotype, data)

    def send_ioctrl_batch(self, channel, commands):
        for iotype, _ in commands:
            if iotype == 256:
                self.phase = 'SD query'
            self.sent[(self.phase, iotype)] += 1
        return super().send_ioctrl_batch(channel, commands)

    def poll_ioctrl(self, timeout=5.0):
        for iotype, data in super().poll_ioctrl(timeout=timeout):
            self.frames[(self.phase, iotype)] += 1
            self.last_frame[(self.phase, iotype)] = time.monotonic() - self.started
            if iotype != 0x10011:
                self.lengths[(self.phase, iotype, len(data))] += 1
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
        print(f'Encoded outbound P4P/KCP packets: {self.encoded_packets}')
        print('Recovered native IOCTRL responses: ' + str(dict(self.recovered)))
        self.transport.report()
        print('Inbound decoded relay datagrams:')
        for kind, count in sorted(self.relay_rx.items()):
            print(f'  0x{kind:08x}: {count}, last +{self.relay_last[kind]:.2f}s')
        print(f'Undrained application buffer: {len(self._app_buf)} bytes')
        print('IOCTRL requests queued (not proof of delivery):')
        for (phase, iotype), count in sorted(self.sent.items()):
            print(f'  {phase}: 0x{iotype:08x} ({iotype}) x {count}')
        print('Decoded frame counts (no payloads):')
        if not self.frames:
            print('  None')
        for (phase, iotype), count in sorted(self.frames.items()):
            print(f'  {phase}: 0x{iotype:08x} ({iotype}) x {count}; '
                  f'last at +{self.last_frame[(phase, iotype)]:.1f}s')
        print('Non-video payload sizes (top 20, no contents):')
        for (phase, iotype, size), count in self.lengths.most_common(20):
            print(f'  {phase}: 0x{iotype:08x}, {size} bytes x {count}')
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
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--events', action='store_true', help='Explicitly request SD events (may wake camera)')
    modes.add_argument('--sdk-events', action='store_true', help='Original SDK event sequence for comparison')
    modes.add_argument('--sd-status', action='store_true', help='Test read-only SD status and settings requests')
    window = parser.add_mutually_exclusive_group()
    window.add_argument('--hours', type=int, default=24)
    window.add_argument('--day', type=dt.date.fromisoformat, help='Calendar day YYYY-MM-DD')
    parser.add_argument('--sd-flow', choices=('app', 'no-av'), default='no-av',
                        help='H4 no-AV default or experimental app sequence')
    parser.add_argument('--download-photo', choices=('thumbnail', 'original'),
                        help='Download one latest activity photo after a successful event list')
    parser.add_argument('--kcp-window', choices=(256, 512), type=int, default=256,
                        help='KCP receive window; default SDK 256, Android observed 512')
    parser.add_argument('--tz', default='Europe/Berlin', help='Time zone for --day (default Europe/Berlin)')
    args = parser.parse_args()
    if args.index < 0 or not 1 <= args.hours <= 168:
        parser.error('index must be nonnegative; hours must be 1–168')
    if args.download_photo and (not args.events or args.sd_flow != 'no-av'):
        parser.error('--download-photo requires --events with the no-av flow')
    sdk_version = version('p4p-camera-sdk')
    print(f'SDK version: {sdk_version}')
    if sdk_version != '0.1.16':
        parser.error('Install the pinned SDK with python -m pip install -r requirements.txt')
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
        if not (args.events or args.sdk_events or args.sd_status):
            return 0
        stage = 'camera relay session / SD status' if args.sd_status else 'camera relay session / SD event listing'
        end = int(time.time())
        begin = end - args.hours * 3600
        if args.day:
            tz = ZoneInfo(args.tz)
            begin = int(dt.datetime.combine(args.day, dt.time.min, tzinfo=tz).timestamp())
            end = int(dt.datetime.combine(args.day + dt.timedelta(days=1), dt.time.min, tzinfo=tz).timestamp())
        session = DiagnosticRelay(device.device_uid, device.device_password)
        started = time.monotonic()
        session.started = started
        original_wrap = sdk_relay.wrap_relay_kcp
        original_decode = sdk_relay.try_decode

        def encoded_wrap(raw, routing_tag):
            session.encoded_packets += 1
            session.transport.observe('out', bytes(raw), time.monotonic() - started)
            return encode(original_wrap(raw, routing_tag))

        def observed_decode(raw):
            plain = original_decode(raw)
            if len(plain) >= 16 and plain[:4] == bytes.fromhex('07181000'):
                kind = int.from_bytes(plain[8:12], 'little')
                elapsed = time.monotonic() - started
                session.relay_rx[kind] += 1
                session.relay_last[kind] = elapsed
                if kind == 0x0042140a:
                    session.transport.observe('in', plain[16:], elapsed)
            return plain

        print('H4 compatibility: encoded outbound KCP; native RDT control recovery')
        print(f'SD flow: {args.sd_flow}; KCP receive window: {args.kcp_window}')
        if args.events or args.sdk_events:
            print(f'Query UTC: {dt.datetime.fromtimestamp(begin, dt.timezone.utc).isoformat()}'
              f' to {dt.datetime.fromtimestamp(end, dt.timezone.utc).isoformat()}')
        try:
            with (contextlib.redirect_stdout(io.StringIO()),
                  contextlib.redirect_stderr(io.StringIO()),
                  patch.object(sdk_relay, 'wrap_relay_kcp', encoded_wrap),
                  patch.object(sdk_relay, 'try_decode', observed_decode)):
                with session:
                    if args.kcp_window != 256:
                        session.kcp.set_window_size(128, args.kcp_window)
                    if args.sd_status:
                        session.wait_for_live_stream()
                        session.phase = 'SD status'
                        session.send_ioctrl(0, IOTYPE_GET_SD_STATUS_REQ, build_get_sd_status())
                        for iotype, _ in session.poll_ioctrl(timeout=10):
                            if iotype == IOTYPE_GET_SD_STATUS_RSP:
                                break
                        session.phase = 'settings read'
                        session.send_ioctrl(0, IOTYPE_GET_ADVANCE_SETTINGS_REQ, bytes(4))
                        for iotype, _ in session.poll_ioctrl(timeout=10):
                            if iotype == IOTYPE_GET_ADVANCE_SETTINGS_RSP:
                                break
                    elif args.sdk_events:
                        events = SdCardClient(session).list_events(begin, end)
                    else:
                        events = list_events_staged(session, begin, end, flow=args.sd_flow)
                        if args.download_photo:
                            stage = 'experimental JPEG download'
                            photos = [e for e in events if e.event_type == 4 and e.length == 65535]
                            if not photos:
                                raise RuntimeError('No activity photo candidate')
                            event = max(photos, key=lambda e: e.start_time)
                            kind = 2 if args.download_photo == 'thumbnail' else 3
                            destination = Path('media') / f'activity_{event.start_time}_{args.download_photo}.jpg'
                            if destination.exists():
                                raise FileExistsError('Local destination already exists')
                            session.stage_notes.append(f'Photo candidate: timestamp={event.start_time}, type={kind}')
                            download_photo(session, event, kind, destination)
        finally:
            print(f'Relay / SD query elapsed: {time.monotonic() - started:.1f} s')
            session.report()
            for note in getattr(session, 'stage_notes', []):
                print(note)
        if args.sd_status:
            for label, expected in [('SD status', IOTYPE_GET_SD_STATUS_RSP),
                                    ('Advanced settings', IOTYPE_GET_ADVANCE_SETTINGS_RSP)]:
                found = any(kind == expected for (_, kind) in session.frames)
                print(f'{label}: {"response received" if found else "no explicit response decoded"}')
            return 0
        print(f'Events returned: {len(events)}')
        if not events:
            print('No events decoded; SD card may still contain recordings.')
        for event in sorted(events, key=lambda e: e.start_time):
            stamp = dt.datetime.fromtimestamp(event.start_time, dt.timezone.utc).isoformat()
            print(f'{stamp} | type={event.event_type} | length={event.length}')
        return 0
    except Exception as exc:
        print(f'Failed during {stage}: {type(exc).__name__}. Raw diagnostic details suppressed.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
