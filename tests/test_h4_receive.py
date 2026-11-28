import struct
import unittest
from collections import deque
from ucon_trailcam_smtp.h4_receive import drain_pending, poll_relay


def frame(code, body):
    return struct.pack('<IIII', 4, 0, len(body), code) + body


class FakeKcp:
    def __init__(self):
        self.queue = deque()

    def receive(self, packet):
        # One datagram releases multiple complete KCP messages.
        self.queue.extend((frame(257, bytes(132)), frame(961, bytes(368))))

    def get_received(self):
        return self.queue.popleft() if self.queue else b''

    def update(self, clock):
        pass

    def flush(self):
        pass


class FakeSocket:
    def __init__(self):
        self.reads = 0

    def settimeout(self, timeout):
        pass

    def recvfrom(self, size):
        self.reads += 1
        if self.reads != 1:
            raise AssertionError('Should not need another UDP packet')
        return struct.pack('<IIII', 0x00101807, 0, 0x0042140A, 0) + b'fixture', None


class Session:
    def __init__(self):
        self.kcp = FakeKcp()
        self.sock = FakeSocket()
        self._app_buf = bytearray()
        self.rx_messages = self.rx_errors = 0

    def _clock(self):
        return 0

    def _drain_frames(self):
        while len(self._app_buf) >= 16:
            _, _, n, code = struct.unpack_from('<IIII', self._app_buf)
            if len(self._app_buf) < 16 + n:
                return
            body = bytes(self._app_buf[16:16 + n])
            del self._app_buf[:16 + n]
            yield code, body


class ReceiveTests(unittest.TestCase):
    def test_two_responses_one_datagram(self):
        session = Session()
        poll = poll_relay(session, lambda p: p, 1)
        self.assertEqual(next(poll), (257, bytes(132)))
        self.assertEqual(next(poll), (961, bytes(368)))
        poll.close()
        self.assertEqual(session.sock.reads, 1)
        self.assertEqual(session.rx_messages, 2)

    def test_pending_after_previous_consumer_stops(self):
        session = Session()
        session.kcp.queue.append(frame(257, b'a') + frame(961, b'b'))
        session.kcp.queue.append(frame(261, b'c'))
        poll = drain_pending(session)
        self.assertEqual(next(poll), (257, b'a'))
        poll.close()
        self.assertEqual(list(drain_pending(session)), [(961, b'b'), (261, b'c')])

    def test_partial_frame_across_kcp_messages(self):
        session = Session()
        packet = frame(257, bytes(132))
        session.kcp.queue.extend((packet[:10], packet[10:]))
        self.assertEqual(list(drain_pending(session)), [(257, bytes(132))])
