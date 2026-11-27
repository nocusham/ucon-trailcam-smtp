import struct
import unittest
from h4_transport import TransportTrace, kcp_segments


def segment(cmd, sn, una=0, body=b'', wnd=512):
    return struct.pack('<IBBHIIII', 7, cmd, 0, wnd, 0, sn, una, len(body)) + body


class TransportTests(unittest.TestCase):
    def test_explicit_and_cumulative_ack(self):
        trace = TransportTrace()
        body = struct.pack('<IIII', 3, 0, 4, 960) + bytes(4)
        trace.observe('out', segment(81, 0, body=body) + segment(81, 1, body=body), 1)
        trace.observe('out', segment(81, 0, body=body), 1.1)
        trace.observe('in', segment(82, 0, una=2), 1.2)
        self.assertEqual(trace.pushes[(7, 0)][2], 2)
        self.assertEqual(trace.acks[(7, 0)], 1.2)
        self.assertEqual(trace.una[(7, 1)], 1.2)

    def test_truncated_segment(self):
        self.assertEqual(list(kcp_segments(segment(81, 0, body=b'ab')[:-1])), [])
