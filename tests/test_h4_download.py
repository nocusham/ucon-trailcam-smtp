import hashlib
import struct
import unittest
from ucon_trailcam_smtp.h4_download import bulk_request, PhotoBlocks, native_frames, transfer_size, check_reference, verify_metadata_md5, native_photo_filename


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

    def test_zero_size_bulk_request_rejected(self):
        with self.assertRaises(ValueError):
            bulk_request(2, 1700000000, 0)

    def test_reference_size_only_overrides_zero(self):
        self.assertEqual(transfer_size(0, 275548), 275548)
        self.assertEqual(transfer_size(275548, 275548), 275548)
        with self.assertRaises(ValueError):
            transfer_size(0)
        with self.assertRaises(ValueError):
            transfer_size(123, 275548)

    def test_reference_hash_must_match(self):
        data = b'fake JPEG for hash test'
        self.assertEqual(check_reference(data, hashlib.sha256(data).hexdigest()),
                         hashlib.sha256(data).hexdigest())
        with self.assertRaises(ValueError):
            check_reference(data, '0' * 64)

    def test_reference_original_request(self):
        req = bulk_request(3, 1700000000, 275548)
        self.assertEqual(struct.unpack_from('<H', req, 1212)[0], 230)
        self.assertEqual(struct.unpack_from('<I', req, 1216)[0], 0)
        self.assertEqual(struct.unpack_from('<I', req, 1220)[0], 275548)

    def test_metadata_md5_required_and_verified(self):
        data = b'synthetic photo data'
        verify_metadata_md5(data, hashlib.md5(data).digest())
        with self.assertRaises(ValueError):
            verify_metadata_md5(data, bytes(16))
        with self.assertRaises(ValueError):
            verify_metadata_md5(data + b'!', hashlib.md5(data).digest())

    def test_native_photo_filename(self):
        name = b'20260101_120000_000_65535_PH.jpg'
        header = bytearray(28)
        struct.pack_into('<H', header, 6, len(name))
        self.assertEqual(native_photo_filename(bytes(header) + name), name.decode())
        for unsafe in (b'../file.jpg', b'a/b.jpg', b'file.exe', b'a..jpg', b'file.jpg\x00'):
            struct.pack_into('<H', header, 6, len(unsafe))
            self.assertIsNone(native_photo_filename(bytes(header) + unsafe))
        self.assertIsNone(native_photo_filename(bytes(header)))
