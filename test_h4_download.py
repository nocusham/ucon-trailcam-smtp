import struct
import unittest
from h4_download import bulk_request, PhotoBlocks, native_frames


class DownloadTests(unittest.TestCase):
    def test_bulk_request(self):
        req = bulk_request(3, 1700000000, 257267)
        self.assertEqual(len(req), 1224)
        self.assertEqual(req[9], 3)
        self.assertEqual(struct.unpack_from('<H', req, 1212)[0], 215)
        self.assertEqual(struct.unpack_from('<I', req, 1220)[0], 257267)

    def test_blocks_out_of_order(self):
        data = b'\xff\xd8' + bytes(1200) + b'\xff\xd9'
        blocks = PhotoBlocks(3, 1700000000, len(data))
        for offset in (1200, 0, 1200):
            payload = data[offset:offset+1200]
            body = bytearray(24)
            struct.pack_into('<I', body, 4, 1700000000)
            body[10] = 3
            struct.pack_into('<II', body, 16, offset, len(payload))
            blocks.add(bytes(body) + payload)
        self.assertEqual(blocks.image(), data)

    def test_native_file_frame_preserved(self):
        body = bytes(24) + b'abc'
        frame = struct.pack('<IIII', 0x1000004, 0, len(body), 263) + body
        class Session:
            _app_buf = bytearray(frame)
        session = Session()
        self.assertEqual(list(native_frames(session)), [(263, body)])
        self.assertEqual(session._app_buf, b'')
