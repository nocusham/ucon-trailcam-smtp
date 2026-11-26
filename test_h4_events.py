"""Synthetic sequence tests; never contacts a camera."""
import struct
import unittest

from h4_events import list_events_staged


class FakeSession:
    def __init__(self, settings=True):
        self.settings = settings
        self.calls = []
        self.av_kwargs = None
        self.phase = ''
        self.polls = 0

    def wait_for_live_stream(self):
        self.calls.append('live')

    def send_ioctrl_batch(self, channel, commands):
        self.calls.append(tuple(i for i, _ in commands))

    def send_avctrl(self, command, **kwargs):
        self.calls.append(('av', command))
        self.av_kwargs = kwargs

    def poll_ioctrl(self, timeout):
        self.polls += 1
        if self.polls == 1 and self.settings:
            yield 961, bytes(368)
        elif self.polls == 4 or (self.polls == 3 and not any(c[0] == 'av' for c in self.calls if isinstance(c, tuple))):
            header = bytearray(12)
            header[7] = 2
            header[8] = 2
            yield 257, bytes(header) + struct.pack('<IHBBIHBB',
                                                   1700000000, 0, 4, 1,
                                                   1700000010, 65535, 3, 1)


class StagedTests(unittest.TestCase):
    def test_wait_then_list_and_keep_zero_length(self):
        session = FakeSession()
        events = list_events_staged(session, 1699999999, 1700000100, flow='app')
        self.assertEqual(session.calls, ['live', (960, 8474),
                                         ('av', 2), (256, 960)])
        self.assertEqual([e.length for e in events], [0, 65535])

    def test_no_list_without_settings_response(self):
        session = FakeSession(settings=False)
        with self.assertRaises(TimeoutError):
            list_events_staged(session, 1699999999, 1700000100)
        self.assertEqual(session.calls, ['live', (960, 8474)])

    def test_no_av_variant(self):
        session = FakeSession()
        events = list_events_staged(session, 1699999999, 1700000100, flow='no-av')
        self.assertEqual(session.calls, ['live', (960, 8474),
                                         (256, 960)])
        self.assertEqual(len(events), 2)

    def test_skip_live_wait(self):
        session = FakeSession()
        events = list_events_staged(session, 1699999999, 1700000100, wait_live=False)
        self.assertEqual(session.calls, [(960, 8474), (256, 960)])
        self.assertEqual(len(events), 2)

    def test_avctrl_audio_flag(self):
        session = FakeSession()
        events = list_events_staged(session, 1699999999, 1700000100,
                                    flow='app', wait_live=False, with_audio=False)
        self.assertEqual(session.av_kwargs['with_audio'], 0)
        self.assertEqual(len(events), 2)
