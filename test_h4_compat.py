import struct
import unittest

from h4_compat import recover_control, is_alive_response


class ControlRecoveryTests(unittest.TestCase):
    def test_list_preserves_first_timestamp_and_final_record(self):
        records = struct.pack('<IHBBIHBB', 1700000000, 98, 3, 1,
                              1700000100, 65535, 4, 1)
        header = bytearray(12)
        header[7] = 2
        body = bytes(header) + records
        frame = struct.pack('<IIII', 4, 0, len(body), 257) + body
        later = b'next'
        kind, recovered = recover_control(frame + later, len(later),
                                          0x10004, frame[32:])
        self.assertEqual((kind, recovered), (257, body))
        self.assertEqual(recovered[12:], records)

    def test_non_control_unchanged(self):
        self.assertEqual(recover_control(b'', 0, 0x10011, b'x'),
                         (0x10011, b'x'))

    def test_unknown_control_unchanged(self):
        body = bytes(32)
        frame = struct.pack('<IIII', 4, 0, len(body), 12345) + body
        self.assertEqual(recover_control(frame, 0, 0x10004, frame[32:]),
                         (0x10004, frame[32:]))

    def test_truncated_list_not_reclassified(self):
        body = bytearray(16)
        body[7] = 2
        frame = struct.pack('<IIII', 4, 0, len(body), 257) + body
        self.assertEqual(recover_control(frame, 0, 0x10004, b''),
                         (0x10004, b''))

    def test_only_compact_alive_is_binding_response(self):
        alive = struct.pack('<III', 0x00101807, 20, 0x00421406) + bytes(24)
        candidate = struct.pack('<III', 0x00101807, 452, 0x00421206) + bytes(456)
        self.assertTrue(is_alive_response(alive))
        self.assertFalse(is_alive_response(candidate))
        self.assertFalse(is_alive_response(alive + bytes(1)))


if __name__ == '__main__':
    unittest.main()
