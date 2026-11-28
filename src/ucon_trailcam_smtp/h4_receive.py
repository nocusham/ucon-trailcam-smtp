"""Drain all available KCP messages, including after the live stream stops."""
import socket
import struct
import time


def drain_pending(session):
    # A caller may have stopped consuming the previous generator at a frame.
    yield from session._drain_frames()
    while True:
        data = session.kcp.get_received()
        if not data:
            return
        session.rx_messages += 1
        session._app_buf.extend(data)
        yield from session._drain_frames()


def poll_relay(session, decode, timeout):
    """Drive transport independently of the arrival of another UDP datagram."""
    assert session.sock is not None and session.kcp is not None
    deadline = time.monotonic() + timeout
    if not hasattr(session, '_h4_last_keepalive'):
        session._h4_last_keepalive = time.monotonic()
    while time.monotonic() < deadline:
        now = time.monotonic()
        if now - session._h4_last_keepalive >= 1.0:
            session.sock.sendto(session.keepalive, session.relay_addr)
            session._h4_last_keepalive = now
        session.kcp.update(session._clock())
        session.kcp.flush()
        yield from drain_pending(session)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            session.sock.settimeout(min(0.05, remaining))
            packet, _ = session.sock.recvfrom(65535)
        except socket.timeout:
            continue
        plain = decode(packet)
        if len(plain) < 16 or struct.unpack_from('<I', plain, 8)[0] != 0x0042140A:
            continue
        try:
            session.kcp.receive(plain[16:])
        except Exception:
            session.rx_errors += 1
            continue
        # Send transport ACKs even if the consumer stops at the next frame.
        session.kcp.flush()
        yield from drain_pending(session)
