"""Read-only staged SD listing, based on H4 Android packet timing."""
import time
from p4p_camera_sdk.sdcard import build_list_event, parse_event_record
from p4p_camera_sdk.sdcard_client import SdCardEvent


def list_events_staged(session, begin, end, flow='no-av'):
    """Wait for settings response before issuing the observed SD sequence.

    Capture: settings + companion, response 961, AVCTRL, list + companion.
    Do not repeat requests automatically, or change persistent settings.
    """
    notes = session.stage_notes = []
    session.wait_for_live_stream()
    session.phase = 'settings init'
    session.send_ioctrl_batch(0, [(960, bytes(4)), (8474, bytes(4))])
    start = time.monotonic()
    for kind, _ in session.poll_ioctrl(timeout=15):
        if kind == 961:
            notes.append(f'Settings response 961 after {time.monotonic() - start:.2f}s')
            break
    else:
        notes.append('No settings response; SD request intentionally not sent.')
        raise TimeoutError('settings init did not receive 961')

    # Continue processing KCP and keepalives during the observed short gap.
    for _ in session.poll_ioctrl(timeout=0.4):
        pass
    if flow == 'app':
        session.phase = 'playback init'
        session.send_avctrl(2, playrecord=0, streamindex=0, with_audio=1,
                            st_time_day=0, param=0)
        for _ in session.poll_ioctrl(timeout=0.03):
            pass
    elif flow == 'no-av':
        notes.append('H4 listing: AVCTRL omitted.')
    else:
        raise ValueError('unknown SD flow')
    session.send_ioctrl_batch(0, [(256, build_list_event(begin, end, 0)),
                                  (960, bytes(4))])
    notes.append('SD list requested after settings response.')
    events = {}
    expected = None
    for kind, body in session.poll_ioctrl(timeout=20):
        if kind != 257 or len(body) < 12:
            continue
        count = body[7]
        total = int.from_bytes(body[8:10], 'little')
        if len(body) < 12 + 8 * count:
            notes.append('Truncated SD response ignored.')
            continue
        expected = total
        for offset in range(12, 12 + 8 * count, 8):
            record = parse_event_record(body[offset:offset + 8])
            event = SdCardEvent(record.start_time, record.length, record.event_type,
                                record.src_event, record.src_status)
            events[(record.start_time, record.length, record.src_event, record.src_status)] = event
        if len(events) >= expected:
            break
    if expected is None:
        notes.append('No decoded SD list response.')
    else:
        notes.append(f'SD response reported total={expected}; unique records={len(events)}')
    return list(events.values())
