import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

from health_alerts import (AlertSettings, build_alert, dispatch_due, due_notices,
                           init_health, observe, parse_alerts)


class HealthAlertTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'health.sqlite3'
        self.db = sqlite3.connect(self.path)
        self.addCleanup(lambda: self.db.close())
        init_health(self.db)
        self.settings = AlertSettings(enabled=True, sender='s@example.invalid', recipient='r@example.invalid')
        self.cameras = {'uid-a': 'cam-a', 'uid-b': 'cam-b'}
        self.send = Mock()

    def check(self, category, scope, now, healthy=False, **kwargs):
        observe(self.db, category, scope, healthy=healthy, now=now, **kwargs)

    def dispatch(self, now, settings=None):
        return dispatch_due(self.db, settings or self.settings, now, self.cameras,
                            self.send, emit=lambda _: None)

    def test_transient_api_never_alerts(self):
        self.check('api', 'ucon', 0)
        self.check('api', 'ucon', 1800, healthy=True)
        self.assertEqual(self.dispatch(3600), (0, 0))
        self.send.assert_not_called()

    def test_api_needs_actual_failures_spanning_threshold(self):
        self.check('api', 'ucon', 0)
        self.assertEqual(self.dispatch(99999), (0, 0))
        self.check('api', 'ucon', 1800)
        self.assertEqual(self.dispatch(1800), (1, 0))

    def test_blocked_login_matures_without_retry(self):
        self.check('login', 'ucon', 0, code=20005, blocked=True)
        self.assertEqual(self.dispatch(899), (0, 0))
        self.assertEqual(self.dispatch(900), (1, 0))
        self.assertIn('20005', self.send.call_args.args[0].get_content())

    def test_camera_isolated_and_requires_confirmed_span(self):
        self.check('camera', 'uid-a', 0)
        self.check('camera', 'uid-b', 0)
        self.check('camera', 'uid-b', 86400, healthy=True)
        self.assertEqual(self.dispatch(86400), (0, 0))
        self.check('camera', 'uid-a', 86400)
        self.assertEqual(self.dispatch(86400), (1, 0))
        msg = self.send.call_args.args[0]
        self.assertIn('cam-a', msg['Subject'])
        self.assertNotIn('uid-a', msg.as_string())
        self.assertEqual(list(msg.iter_attachments()), [])

    def test_repeat_and_restart(self):
        self.check('login', 'ucon', 0, code=20005, blocked=True)
        self.dispatch(900)
        self.db.close()
        self.db = sqlite3.connect(self.path)
        init_health(self.db)
        self.assertEqual(self.dispatch(901), (0, 0))
        self.assertEqual(self.dispatch(900 + 86400), (1, 0))
        self.assertEqual(self.send.call_count, 2)

    def test_recovery_once_and_new_incident(self):
        self.check('login', 'ucon', 0, code=20005, blocked=True)
        self.dispatch(900)
        self.check('login', 'ucon', 901, healthy=True)
        self.assertEqual(self.dispatch(901), (1, 0))
        self.assertIn('Entwarnung', self.send.call_args.args[0]['Subject'])
        self.assertEqual(self.dispatch(902), (0, 0))
        self.check('login', 'ucon', 903, code=20005, blocked=True)
        self.assertEqual(self.dispatch(1803), (1, 0))

    def test_failed_alarm_retry_throttled(self):
        self.check('login', 'ucon', 0, code=20005, blocked=True)
        self.send.side_effect = TimeoutError
        self.assertEqual(self.dispatch(900), (0, 1))
        self.assertEqual(self.dispatch(4499), (0, 0))
        self.send.side_effect = None
        self.assertEqual(self.dispatch(4500), (1, 0))

    def test_disabled_and_unknown_camera(self):
        self.check('camera', 'unknown', 0)
        self.check('camera', 'unknown', 86400)
        self.check('login', 'ucon', 0, code=20005, blocked=True)
        self.assertEqual(self.dispatch(86400, replace(self.settings, enabled=False)), (0, 0))
        self.assertEqual(len(due_notices(self.db, self.settings, 86400, self.cameras)), 1)

    def test_recovery_disabled(self):
        self.check('login', 'ucon', 0, code=20005, blocked=True)
        self.dispatch(900)
        self.check('login', 'ucon', 901, healthy=True)
        self.assertEqual(self.dispatch(901, replace(self.settings, recovery=False)), (0, 0))

    def test_config_optional_and_strict(self):
        self.assertFalse(parse_alerts(None).enabled)
        raw = {'enabled': True, 'smtp': {'host': 'smtp.example.invalid', 'from': 's@example.invalid',
                                         'to': 'r@example.invalid', 'username': 'u', 'password_env': 'ALERT_PASS'}}
        self.assertEqual(parse_alerts(raw).password_env, 'ALERT_PASS')
        for change in ({'security': 'none'}, {'to': 'r@revierwelt.de'}, {'host': 'smtp.revierwelt.de'},
                       {'password': 'secret'}, {'password_env': ''}, {'to': 'a@x.invalid,b@y.invalid'}):
            with self.assertRaises(ValueError):
                parse_alerts({**raw, 'smtp': {**raw['smtp'], **change}})
        with self.assertRaises(ValueError):
            parse_alerts({**raw, 'login_minutes': True})

    def test_manual_test_plain_text(self):
        msg = build_alert(self.settings)
        self.assertEqual(msg.get_content_type(), 'text/plain')
        self.assertEqual(msg['To'], 'r@example.invalid')
        self.assertIn('SMTP-Alarmtest', msg.get_content())
