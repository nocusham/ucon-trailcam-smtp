"""H4 P4P tail permutation correction for the pinned SDK 0.1.16.

Full 16-byte blocks are unchanged. The native implementation also permutes
power-of-two tails of 2, 4 and 8 bytes after XOR. Derived from repeated
KCP segments in private captures; no capture bytes or device secrets bundled.
"""
from p4p_camera_sdk.p4p_crypto import encode as _sdk_encode, decode as _sdk_decode

TAIL_PERM = {
    2: (1, 0),
    4: (2, 3, 0, 1),
    8: (7, 4, 3, 2, 1, 6, 5, 0),
}


def encode(data: bytes) -> bytes:
    encoded = _sdk_encode(data)
    perm = TAIL_PERM.get(len(encoded) % 16)
    if perm is None:
        return encoded
    start = len(encoded) - len(perm)
    return encoded[:start] + bytes(encoded[start + i] for i in perm)


def decode(data: bytes) -> bytes:
    perm = TAIL_PERM.get(len(data) % 16)
    if perm is None:
        return _sdk_decode(data)
    start = len(data) - len(perm)
    restored = bytearray(data)
    for j, i in enumerate(perm):
        restored[start + i] = data[start + j]
    return _sdk_decode(bytes(restored))
