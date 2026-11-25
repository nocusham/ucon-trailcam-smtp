"""Safe KCP diagnostics: no raw payloads, session IDs or addresses printed."""
import struct
from collections import Counter


def kcp_segments(data):
    pos = 0
    while pos + 24 <= len(data):
        conv, cmd, frg, wnd, ts, sn, una, size = struct.unpack_from('<IBBHIIII', data, pos)
        if cmd not in (81, 82, 83, 84) or size > len(data) - pos - 24:
            return
        yield conv, cmd, frg, wnd, sn, una, data[pos + 24:pos + 24 + size]
        pos += 24 + size


class TransportTrace:
    def __init__(self):
        self.counts = Counter()
        self.last = {}
        self.pushes = {}
        self.acks = {}
        self.una = {}

    def observe(self, direction, data, elapsed):
        for conv, cmd, frg, wnd, sn, una, body in kcp_segments(data):
            self.counts[(direction, cmd)] += 1
            self.last[(direction, cmd)] = elapsed
            key = (conv, sn)
            if direction == 'out' and cmd == 81:
                if key not in self.pushes:
                    label = 'fragment/other'
                    if len(body) >= 16:
                        marker, _, size, code = struct.unpack_from('<IIII', body)
                        if marker == 3 and size <= len(body) - 16:
                            label = f'IOCTRL {code}'
                        elif marker == 1 and size == 16 and len(body) >= 32:
                            label = f'AVCTRL {body[16]}'
                    self.pushes[key] = [label, elapsed, 0, wnd]
                self.pushes[key][2] += 1
            if direction == 'in':
                if cmd == 82:
                    self.acks.setdefault(key, elapsed)
                # KCP UNA is the next expected sequence number.
                for sent_key in self.pushes:
                    if sent_key[0] == conv and 0 < ((una - sent_key[1]) & 0xffffffff) < 0x80000000:
                        self.una.setdefault(sent_key, elapsed)

    def report(self):
        print('KCP transport segments (no payloads):')
        for key, count in sorted(self.counts.items()):
            direction, cmd = key
            print(f'  {direction} cmd={cmd}: {count}, last +{self.last[key]:.2f}s')
        print('Outbound KCP PUSH acknowledgement status:')
        for key, (label, elapsed, repeats, wnd) in sorted(self.pushes.items(), key=lambda item: item[1][1]):
            ack = self.acks.get(key)
            una = self.una.get(key)
            result = f'ACK +{ack-elapsed:.3f}s' if ack is not None else (
                f'UNA +{una-elapsed:.3f}s' if una is not None else 'not observed')
            print(f'  sn={key[1]} {label} at +{elapsed:.2f}s, sends={repeats}, wnd={wnd}: {result}')
