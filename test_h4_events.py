"""Synthetic sequence tests; never contacts a camera."""
import struct
import unittest

from h4_events import list_events_staged


class FakeSession:
    def __init__(self, settings=True):
        self.settings = settings
        self.calls = []
        self.phase = ''
        self.polls = 0

    def wait_for_live_stream(self):
        self.calls.append('live')

    def send_ioctrl_batch(self, channel, commands):
        self.calls.append(tuple(i for i, _ in commands))

    def send_avctrl(self, command, **kwargs):
        self.calls.append(('av', command))

    def poll_ioctrl(self, timeout):
        self.polls += 1
        if self.polls == 1 and self.settings:
            yield 961, bytes(368)
        elif self.polls == 4:
            header = bytearray(12)
            header[7] = 2
            header[8] = 2
            yield 257, bytes(header) + struct.pack('<IHBBIHBB',
                                                   1700000000, 0, 4, 1,
                                                   1700000010, 65535, 3, 1)


class StagedTests(unittest.TestCase):
    def test_wait_then_list_and_keep_zero_length(self):
        session = FakeSession()
        events = list_events_staged(session, 1699999999, 1700000100)
        self.assertEqual(session.calls, ['live', (960, 0x07074C3F),
                                         ('av', 2), (256, 0x07074C3F)])
        self.assertEqual([e.length for e in events], [0, 65535])

    def test_no_list_without_settings_response(self):
        session = FakeSession(settings=False)
        with self.assertRaises(TimeoutError):
            list_events_staged(session, 1699999999, 1700000100)
        self.assertEqual(session.calls, ['live', (960, 0x07074C3F)])
