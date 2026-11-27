import unittest
from p4p_camera_sdk.p4p_crypto import encode as legacy_encode
from h4_crypto import encode, decode


class CryptoTests(unittest.TestCase):
    def test_known_synthetic_tail_vectors(self):
        # XOR of a zero tail with the public SDK key, then native permutation.
        for n, expected in [(2, '2049'), (4, '62654920'),
                            (8, '766c656220656949')]:
            with self.subTest(n=n):
                self.assertEqual(encode(bytes(n)), bytes.fromhex(expected))
                self.assertEqual(decode(bytes.fromhex(expected)), bytes(n))

    def test_roundtrip_all_remainders_and_full_blocks(self):
        for n in range(65):
            data = bytes((i * 19 + 7) % 256 for i in range(n))
            self.assertEqual(decode(encode(data)), data)
            if n % 16 not in (2, 4, 8):
                self.assertEqual(encode(data), legacy_encode(data))

    def test_full_block_prefix_unchanged(self):
        data = bytes(range(40))
        self.assertEqual(encode(data)[:32], legacy_encode(data)[:32])
        self.assertNotEqual(encode(data)[32:], legacy_encode(data)[32:])
