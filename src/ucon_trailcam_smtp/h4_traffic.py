"""Count UDP traffic at the relay socket, without logging packet contents."""
import socket
from collections import Counter


class TrafficStats:
    def __init__(self, phase):
        self.phase = phase
        self.bytes = Counter()
        self.packets = Counter()
        self.frames = Counter()

    def record(self, direction, size):
        key = (self.phase(), direction)
        self.bytes[key] += size
        self.packets[key] += 1

    def report(self):
        print('Traffic statistics (server-side IPv4 UDP; not SIM billing):')
        for phase in sorted({phase for phase, _ in self.packets}):
            rx = self.bytes[(phase, 'rx')]
            tx = self.bytes[(phase, 'tx')]
            n = self.packets[(phase, 'rx')] + self.packets[(phase, 'tx')]
            print(f'  {phase}: RX={rx} B TX={tx} B IP+UDP estimate={rx+tx+28*n} B')
        rx = sum(v for (_, direction), v in self.bytes.items() if direction == 'rx')
        tx = sum(v for (_, direction), v in self.bytes.items() if direction == 'tx')
        total = rx + tx + 28 * sum(self.packets.values())
        print(f'  TOTAL: RX={rx} B TX={tx} B IPv4+UDP estimate={total} B ({total/1000:.1f} kB)')
        for (phase, kind), size in sorted(self.frames.items()):
            print(f'  Decoded media payload {phase} {kind}: {size} B')


class SocketModuleProxy:
    """Only replace socket construction in the relay module; no global socket patch."""
    def __init__(self, stats):
        self.stats = stats

    def __getattr__(self, name):
        return getattr(socket, name)

    def socket(self, *args, **kwargs):
        stats = self.stats

        class MeteredSocket(socket.socket):
            def sendto(self, data, *args, **kwargs):
                n = super().sendto(data, *args, **kwargs)
                stats.record('tx', n)
                return n

            def recvfrom(self, *args, **kwargs):
                data, addr = super().recvfrom(*args, **kwargs)
                stats.record('rx', len(data))
                return data, addr

        return MeteredSocket(*args, **kwargs)
