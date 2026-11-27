import datetime as dt
import unittest
from ucon_trailcam_smtp.mail_subject import camera_subject


def stamp(iso):
    return int(dt.datetime.fromisoformat(iso).timestamp())


class SubjectTests(unittest.TestCase):
    def test_winter_capture_time(self):
        self.assertEqual(camera_subject('testkamera', [stamp('2026-01-15T13:52:05+00:00')]),
                         'UCON testkamera - 15.01.2026 14:52:05 MEZ')

    def test_summer_capture_time(self):
        self.assertEqual(camera_subject('testkamera', [stamp('2026-07-15T13:52:05+00:00')]),
                         'UCON testkamera - 15.07.2026 15:52:05 MESZ')

    def test_clock_change_distinct(self):
        first = camera_subject('testkamera', [stamp('2026-10-25T00:30:00+00:00')])
        second = camera_subject('testkamera', [stamp('2026-10-25T01:30:00+00:00')])
        self.assertTrue(first.endswith('02:30:00 MESZ'))
        self.assertTrue(second.endswith('02:30:00 MEZ'))

    def test_grouped_sorted_range_and_name_validation(self):
        self.assertEqual(camera_subject('testkamera', [200, 100], grouped=True),
                         'UCON testkamera - 2 Originalbilder - 01.01.1970 01:01:40 MEZ bis 01.01.1970 01:03:20 MEZ')
        self.assertEqual(camera_subject('testkamera', [100], grouped=True),
                         'UCON testkamera - 1 Originalbild - 01.01.1970 01:01:40 MEZ')
        with self.assertRaises(ValueError):
            camera_subject('bad\nname', [100])
        with self.assertRaises(ValueError):
            camera_subject('testkamera', [])
