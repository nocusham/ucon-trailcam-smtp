"""H4 relay compatibility helpers, based on private app captures.

No device credentials, packet dumps or media are included.
"""
import struct


def recover_control(before, remaining_length, kind, payload):
    """Recover native IOCTRL ID and complete body from SDK RDT control output.

    RDT control uses a 16-byte prefix: marker, reserved, body length, IOCTRL
    command. The upstream SDK strips 32 bytes, including the first 16 bytes
    of the IOCTRL body. Only map the read responses verified in captures.
    """
    if kind != 0x10004:
        return kind, payload
    end = len(before) - remaining_length
    start = end - len(payload) - 32
    if start < 0 or end > len(before):
        return kind, payload
    marker, reserved, size, command = struct.unpack_from('<IIII', before, start)
    if marker != 4 or size != len(payload) + 16:
        return kind, payload
    if command not in (257, 521, 961):
        return kind, payload
    body = before[start + 16:end]
    if command == 257 and (len(body) < 12 or len(body) < 12 + body[7] * 8):
        return kind, payload
    return command, body


def is_alive_response(plain):
    """H4 KCP binding comes from the compact 36-byte alive reply only."""
    return (len(plain) == 36 and plain[:4] == b'\x07\x18\x10\x00'
            and struct.unpack_from('<I', plain, 8)[0] == 0x00421406)


def matches_requested_conv(plain, requested):
    """H4 captures echo the four proposed conversation bytes at alive offset 24.

    Fail closed if the request is not known or the reply belongs to a
    different conversation. Do not infer a routing tag from a data packet.
    """
    return (is_alive_response(plain) and requested is not None
            and len(requested) == 4 and plain[24:28] == requested)
