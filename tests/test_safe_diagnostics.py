import smtplib
import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from safe_diagnostics import cloud_fields, error_fields, error_kind
from smtp_transport import SafeSMTPFailure, smtp_failure_fields, transmit


class DiagnosticTests(unittest.TestCase):
    def test_http_and_api_numeric_fields(self):
        self.assertEqual(cloud_fields(SimpleNamespace(stage='cloud event list', http_status=503)),
                         'stage=cloud_event_list category=http_status http_status=503')
        self.assertEqual(cloud_fields(SimpleNamespace(stage='login', api_code=20005)),
                         'stage=login category=api_code api_code=20005')

    def test_untrusted_strings_and_numbers_not_logged(self):
        for value in ('secret\nforged log', True, 10**100, None):
            exc = SimpleNamespace(stage=value, diagnostic_kind=value, http_status=value, api_code=value)
            self.assertEqual(cloud_fields(exc), 'stage=unknown category=unexpected')
        exc = SafeSMTPFailure('private', stage='secret', kind='secret', smtp_status='secret', os_errno=True)
        self.assertEqual(smtp_failure_fields(exc), 'stage=unknown category=unknown')

    def test_transport_kinds_and_no_exception_message(self):
        for cls, kind in ((httpx.ConnectTimeout, 'connect_timeout'), (httpx.ReadTimeout, 'read_timeout'),
                          (httpx.ConnectError, 'connect_error'), (httpx.RemoteProtocolError, 'protocol_error')):
            exc = cls('https://private.invalid/?token=secret\nforged')
            self.assertEqual(error_fields(exc), 'category=' + kind)
        self.assertEqual(error_fields(PermissionError(13, 'private', '/secret/path')),
                         'category=permission_error errno=13')
        self.assertEqual(error_fields(sqlite3.OperationalError('private')), 'category=database_error')
        PrivateError = type('secret', (Exception,), {})
        self.assertEqual(error_fields(PrivateError('private')), 'category=unexpected')

    def test_smtp_auth_error_retains_only_safe_fields(self):
        with patch('smtp_transport.smtplib.SMTP') as factory:
            client = factory.return_value.__enter__.return_value
            client.login.side_effect = smtplib.SMTPAuthenticationError(535, b'private credentials')
            with self.assertRaises(SafeSMTPFailure) as caught:
                transmit(object(), 'private.invalid', 587, 'starttls', 'private', 'secret')
            client.send_message.assert_not_called()
        self.assertEqual(smtp_failure_fields(caught.exception), 'stage=auth category=smtp_auth smtp_status=535')
        self.assertNotIn('private', str(caught.exception))

    def test_submission_still_uncertain(self):
        with patch('smtp_transport.smtplib.SMTP') as factory:
            client = factory.return_value.__enter__.return_value
            client.send_message.side_effect = smtplib.SMTPDataError(451, b'private response')
            with self.assertRaises(smtplib.SMTPDataError) as caught:
                transmit(object(), 'private.invalid', 587, 'starttls')
        self.assertEqual(smtp_failure_fields(caught.exception), 'category=smtp_response smtp_status=451')
        self.assertNotIsInstance(caught.exception, SafeSMTPFailure)

    def test_starttls_failure_and_quit_after_acceptance(self):
        with patch('smtp_transport.smtplib.SMTP') as factory:
            client = factory.return_value.__enter__.return_value
            client.starttls.side_effect = TimeoutError('private')
            with self.assertRaises(SafeSMTPFailure) as caught:
                transmit(object(), 'private.invalid', 587, 'starttls')
            self.assertEqual(smtp_failure_fields(caught.exception), 'stage=starttls category=timeout')
            client.starttls.side_effect = None
            client.send_message.return_value = {}
            factory.return_value.__exit__.side_effect = OSError('private')
            transmit(object(), 'private.invalid', 587, 'starttls')
