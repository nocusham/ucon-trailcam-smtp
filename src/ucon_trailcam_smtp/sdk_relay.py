"""Shared H4 relay adapter for the pinned P4P SDK."""

import contextlib
import io
import time
from collections import Counter
from unittest.mock import patch

from p4p_camera_sdk.relay import RelaySession
import p4p_camera_sdk.relay as sdk_relay
import p4p_camera_sdk.p4p_crypto as sdk_crypto

from ucon_trailcam_smtp.h4_compat import recover_control, is_alive_response, matches_requested_conv
from ucon_trailcam_smtp.h4_crypto import encode, decode
from ucon_trailcam_smtp.h4_download import native_frames
from ucon_trailcam_smtp.h4_receive import poll_relay
from ucon_trailcam_smtp.h4_traffic import TrafficStats, SocketModuleProxy
from ucon_trailcam_smtp.h4_transport import TransportTrace, kcp_segments


class DiagnosticRelay(RelaySession):
    """Collect only frame types, lengths and SD counters, never payloads."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.phase = 'initial'
        self.traffic = TrafficStats(lambda: self.phase)
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
        self.binding_replies = Counter()
        self.binding_conv = None
        self.requested_conv = None
        self.inbound_conv = Counter()
        self.rx_messages = self.rx_errors = 0

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
        for iotype, data in poll_relay(self, sdk_relay.try_decode, timeout):
            self.frames[(self.phase, iotype)] += 1
            self.last_frame[(self.phase, iotype)] = time.monotonic() - self.started
            if iotype in (0x10011, 0x10013):
                self.traffic.frames[(self.phase, 'video' if iotype == 0x10011 else 'audio/metadata')] += len(data)
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
        self.traffic.report()
        print(f'Encoded outbound P4P/KCP packets: {self.encoded_packets}')
        print('Recovered native IOCTRL responses: ' + str(dict(self.recovered)))
        print('Relay binding replies: ' + str(dict(self.binding_replies)))
        if self.binding_conv is not None:
            matching = self.inbound_conv[self.binding_conv]
            print(f'Inbound KCP segments matching selected conversation: '
                  f'{matching}/{sum(self.inbound_conv.values())}')
        self.transport.report()
        print('Inbound decoded relay datagrams:')
        for kind, count in sorted(self.relay_rx.items()):
            print(f'  0x{kind:08x}: {count}, last +{self.relay_last[kind]:.2f}s')
        print(f'KCP messages drained: {self.rx_messages}; receive errors: {self.rx_errors}')
        if self.kcp is not None:
            print(f'Next queued KCP message size: {self.kcp.get_next_packet_size()}')
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


@contextlib.contextmanager
def relay_compat(session):
    """Scoped H4 SDK patches; caller owns one sequential relay session."""
    started = session.started
    original_wrap = sdk_relay.wrap_relay_kcp
    original_decode = sdk_relay.try_decode
    original_parse = sdk_relay.parse_rlystreamrsp
    original_streamreq = sdk_relay.build_rlystreamreq

    def observed_streamreq(uid, password, conv4, local_ip='0.0.0.0', local_port=0):
        session.requested_conv = bytes(conv4)
        return original_streamreq(uid, password, conv4, local_ip, local_port)

    def compact_binding(plain):
        if not is_alive_response(plain):
            session.binding_replies['ignored candidate or unexpected reply'] += 1
            return None
        if not matches_requested_conv(plain, session.requested_conv):
            session.binding_replies['ignored nonmatching conversation'] += 1
            return None
        reply = original_parse(plain)
        if reply is not None:
            session.binding_replies['accepted compact alive'] += 1
            session.binding_conv = int.from_bytes(reply['conv'], 'little')
        return reply

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
                for conv, *_ in kcp_segments(plain[16:]):
                    session.inbound_conv[conv] += 1
        return plain

    with (contextlib.redirect_stdout(io.StringIO()),
          contextlib.redirect_stderr(io.StringIO()),
          patch.object(sdk_relay, 'socket', SocketModuleProxy(session.traffic)),
          patch.object(sdk_crypto, 'encode', encode),
          patch.object(sdk_crypto, 'decode', decode),
          patch.object(sdk_relay, 'encode', encode),
          patch.object(sdk_relay, 'decode', decode),
          patch.object(sdk_relay, 'wrap_relay_kcp', encoded_wrap),
          patch.object(sdk_relay, 'try_decode', observed_decode),
          patch.object(sdk_relay, 'build_rlystreamreq', observed_streamreq),
          patch.object(sdk_relay, 'parse_rlystreamrsp', compact_binding)):
        yield
