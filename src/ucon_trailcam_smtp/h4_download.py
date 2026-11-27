"""Experimental one-photo H4 transfer, using the Android capture's bulk request."""
import hashlib
import re
import struct
import time
from pathlib import Path
from ucon_trailcam_smtp.sdk_sdcard import build_download_sd_file

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


def transfer_size(reported, reference_size=None):
    """Do not substitute a different positive size, or guess a missing size."""
    if reference_size is not None and not 0 < reference_size <= MAX_SIZE:
        raise ValueError('Invalid reference size')
    if reported == 0 and reference_size is not None:
        return reference_size
    if not 0 < reported <= MAX_SIZE:
        raise ValueError('Invalid reported size')
    if reference_size is not None and reported != reference_size:
        raise ValueError('Reported size differs from reference')
    return reported


def verify_metadata_md5(data, checksum):
    """The 16 bytes at offsets 12..27 of successful 261 are the file MD5."""
    if len(checksum) != 16 or not any(checksum):
        raise ValueError('Missing file MD5')
    if hashlib.md5(data).digest() != checksum:
        raise ValueError('File MD5 mismatch')


def check_reference(data, reference_sha256):
    actual = hashlib.sha256(data).hexdigest()
    if reference_sha256 is not None and actual != reference_sha256.lower():
        raise ValueError('Reference SHA256 mismatch')
    return actual


def native_photo_filename(body):
    """Return a safe camera basename from the 261 metadata or None."""
    if len(body) < 28:
        return None
    length = struct.unpack_from('<H', body, 6)[0]
    if not 1 <= length <= 128 or len(body) < 28 + length:
        return None
    try:
        name = body[28:28 + length].decode('ascii')
    except UnicodeDecodeError:
        return None
    if '..' in name or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*\.(?i:jpg|jpeg)', name):
        return None
    return name


def download_photo(session, event, file_type, destination, *,
                   reference_size=None, reference_sha256=None, preserve_filename=False,
                   require_native_filename=False):
    if require_native_filename and (not preserve_filename or file_type != 3):
        raise ValueError('Native filename requirement applies to originals only')
    if (reference_size is None) != (reference_sha256 is None):
        raise ValueError('Reference size and hash must be supplied together')
    if reference_size is not None and file_type != 3:
        raise ValueError('Reference override restricted to original photos')
    notes = session.stage_notes
    session.phase = 'photo metadata'
    session.native_download = True
    payload = build_download_sd_file(file_type, event.start_time,
                                     event.length, event.src_event, event.src_status)
    session.send_ioctrl(0, 260, payload)
    size = None
    for kind, body in session.poll_ioctrl(timeout=15):
        if kind == 261 and len(body) >= 28:
            size = struct.unpack_from('<I', body, 8)[0]
            checksum = body[12:28]
            flag = body[7]
            break
    if size is None:
        raise TimeoutError('No file metadata response 261')
    notes.append(f'Photo metadata: size={size} bytes; checksum flag={flag}; '
                 f'body_length={len(body)}; filename_length={body[6]}')
    if size == 0 and reference_size is None:
        notes.append('Camera reported zero file size; data request not sent.')
    if size == 0 and reference_size is not None:
        notes.append('Reference experiment: zero-size metadata; using independently known size.')
    if reference_size is not None and size not in (0, reference_size):
        notes.append('Reported nonzero size differs from reference; stopping.')
    reported_size = size
    size = transfer_size(size, reference_size)
    notes.append(f'Data request: timestamp={event.start_time}, file_type={file_type}, '
                 f'size={size}, blocks={(size + CHUNK - 1)//CHUNK}')
    if reported_size > 0 and not any(checksum):
        notes.append('Metadata MD5 absent; data request not sent.')
        raise ValueError('Missing file MD5')
    destination = Path(destination)
    if preserve_filename and file_type == 3:
        name = native_photo_filename(body)
        if name:
            destination = destination.with_name(name)
            notes.append('Using camera-reported photo basename.')
        else:
            if require_native_filename:
                raise ValueError('Missing or unsafe native filename; original refused')
            notes.append('Missing or unsafe camera filename; using generated basename.')
    if destination.exists():
        raise FileExistsError('Local destination already exists')
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
    if reported_size > 0:
        try:
            verify_metadata_md5(data, checksum)
        except ValueError:
            notes.append('Metadata MD5 missing or mismatched; no file saved.')
            raise
        notes.append('Metadata MD5: exact match')
    actual = hashlib.sha256(data).hexdigest()
    notes.append(f'JPEG size/signature checked; SHA256={actual}')
    if reference_sha256 is not None:
        if actual != reference_sha256.lower():
            notes.append('Reference SHA256 mismatch; no file saved.')
        check_reference(data, reference_sha256)
        notes.append('Reference SHA256: exact match')
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('xb') as f:
        f.write(data)
    notes.append(f'JPEG saved locally: {destination}')
    return destination
