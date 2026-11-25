"""Experimental one-photo H4 transfer, using the Android capture's bulk request."""
import hashlib
import struct
import time
from pathlib import Path
from p4p_camera_sdk.sdcard import build_download_sd_file

CHUNK = 1200
MAX_SIZE = 16 * 1024 * 1024


def native_frames(session):
    """Drain H4 frames without stripping the native file-data header."""
    while len(session._app_buf) >= 16:
        buf = session._app_buf
        marker, _, size, code = struct.unpack_from('<IIII', buf)
        if marker not in (2, 3, 4, 0x11, 0x13, 0x14, 0x15, 0x1000004) or size > MAX_SIZE:
            raise ValueError('Unknown native frame or invalid size during download')
        if len(buf) < 16 + size:
            return
        body = bytes(buf[16:16 + size])
        session._app_buf = buf[16 + size:]
        if marker in (3, 4) or (marker == 0x1000004 and code == 263):
            yield code, body
        elif marker in (0x11, 0x13, 0x14, 0x15):
            yield 0x10000 + marker, body[16:]
        else:
            yield 0x10000 + marker, body


def bulk_request(file_type, timestamp, size):
    """One request for the entire file; count at 1212, total size at 1220."""
    if not 0 < size <= MAX_SIZE:
        raise ValueError('File size outside test limits')
    count = (size + CHUNK - 1) // CHUNK
    data = bytearray(1224)
    struct.pack_into('<I', data, 4, timestamp)
    data[9] = file_type
    struct.pack_into('<H', data, 1212, count)
    struct.pack_into('<I', data, 1220, size)
    return bytes(data)


class PhotoBlocks:
    def __init__(self, file_type, timestamp, size):
        self.file_type = file_type
        self.timestamp = timestamp
        self.size = size
        self.parts = {}

    def add(self, body):
        if len(body) < 24:
            return
        ts = struct.unpack_from('<I', body, 4)[0]
        offset, length = struct.unpack_from('<II', body, 16)
        if ts != self.timestamp or body[10] != self.file_type:
            return
        if (offset % CHUNK or offset >= self.size or
                length != min(CHUNK, self.size - offset) or len(body) < 24 + length):
            raise ValueError('Invalid JPEG block bounds')
        block = body[24:24 + length]
        if offset in self.parts and self.parts[offset] != block:
            raise ValueError('Conflicting duplicate JPEG block')
        self.parts[offset] = block

    @property
    def complete(self):
        return len(self.parts) == (self.size + CHUNK - 1) // CHUNK

    def image(self):
        if not self.complete:
            raise TimeoutError('JPEG transfer incomplete')
        data = b''.join(self.parts[o] for o in range(0, self.size, CHUNK))
        if len(data) != self.size or not data.startswith(b'\xff\xd8') or not data.endswith(b'\xff\xd9'):
            raise ValueError('JPEG size or signature invalid')
        return data


def download_photo(session, event, file_type, destination):
    notes = session.stage_notes
    session.phase = 'photo metadata'
    session.native_download = True
    session.send_ioctrl(0, 260, build_download_sd_file(file_type, event.start_time,
                         event.length, event.src_event, event.src_status))
    size = None
    for kind, body in session.poll_ioctrl(timeout=15):
        if kind == 261 and len(body) >= 28:
            size = struct.unpack_from('<I', body, 8)[0]
            checksum = body[12:28]
            flag = body[7]
            break
    if size is None:
        raise TimeoutError('No file metadata response 261')
    notes.append(f'Photo metadata: size={size} bytes; checksum flag={flag}')
    request = bulk_request(file_type, event.start_time, size)
    blocks = PhotoBlocks(file_type, event.start_time, size)
    session.phase = 'photo data'
    session.send_ioctrl(0, 262, request)
    try:
        for kind, body in session.poll_ioctrl(timeout=45):
            if kind == 263:
                blocks.add(body)
                if blocks.complete:
                    break
    finally:
        notes.append(f'JPEG blocks: {len(blocks.parts)}/{(size + CHUNK - 1)//CHUNK}')
    data = blocks.image()
    match = hashlib.md5(data).digest() == checksum
    notes.append(f'Metadata MD5 comparison: {"match" if match else "mismatch (semantics unverified)"}')
    notes.append(f'JPEG size/signature checked; SHA256={hashlib.sha256(data).hexdigest()}')
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('xb') as f:
        f.write(data)
    notes.append(f'JPEG saved locally: {destination}')
    return destination
