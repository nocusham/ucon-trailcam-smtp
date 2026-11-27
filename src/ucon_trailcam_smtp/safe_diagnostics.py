"""Allowlisted diagnostic fields; never format exception messages or responses."""
import smtplib
import sqlite3
import ssl

import httpx


KINDS = (
    'http_status', 'api_code', 'invalid_json', 'invalid_schema',
    'camera_selection', 'metadata_rejected', 'transport', 'connect_timeout',
    'read_timeout', 'write_timeout', 'pool_timeout', 'timeout', 'connect_error',
    'read_error', 'write_error', 'protocol_error', 'network_error',
    'tls_error', 'smtp_auth', 'smtp_response', 'smtp_disconnect', 'smtp_error',
    'database_error', 'permission_error', 'file_missing', 'os_error',
    'invalid_value', 'interrupted', 'unexpected',
)
CLOUD_STAGES = ('login', 'device discovery', 'cloud event list')
SMTP_STAGES = ('tls_context', 'connect', 'ehlo', 'starttls', 'auth', 'submission')


def allowed(value, choices):
    return value if type(value) is str and value in choices else 'unknown'


def number_field(name, value, minimum, maximum):
    return f' {name}={value}' if type(value) is int and minimum <= value <= maximum else ''


def error_kind(exc):
    for cls, kind in (
        (KeyboardInterrupt, 'interrupted'),
        (httpx.ConnectTimeout, 'connect_timeout'), (httpx.ReadTimeout, 'read_timeout'),
        (httpx.WriteTimeout, 'write_timeout'), (httpx.PoolTimeout, 'pool_timeout'),
        (httpx.TimeoutException, 'timeout'), (httpx.ConnectError, 'connect_error'),
        (httpx.ReadError, 'read_error'), (httpx.WriteError, 'write_error'),
        (httpx.ProtocolError, 'protocol_error'), (httpx.NetworkError, 'network_error'),
        (httpx.HTTPError, 'transport'), (ssl.SSLError, 'tls_error'),
        (smtplib.SMTPAuthenticationError, 'smtp_auth'),
        (smtplib.SMTPResponseException, 'smtp_response'),
        (smtplib.SMTPServerDisconnected, 'smtp_disconnect'),
        (smtplib.SMTPException, 'smtp_error'), (sqlite3.Error, 'database_error'),
        (TimeoutError, 'timeout'), (PermissionError, 'permission_error'),
        (FileNotFoundError, 'file_missing'), (OSError, 'os_error'),
        (ValueError, 'invalid_value'),
    ):
        if isinstance(exc, cls):
            return kind
    return 'unexpected'


def error_fields(exc):
    result = f'category={error_kind(exc)}'
    if isinstance(exc, smtplib.SMTPResponseException):
        result += number_field('smtp_status', exc.smtp_code, 100, 599)
    if isinstance(exc, OSError):
        result += number_field('errno', exc.errno, 1, 65535)
    if isinstance(exc, sqlite3.Error):
        result += number_field('sqlite_code', getattr(exc, 'sqlite_errorcode', None), 1, 65535)
    return result


def cloud_fields(exc):
    stage = allowed(getattr(exc, 'stage', None), CLOUD_STAGES).replace(' ', '_')
    http_status = getattr(exc, 'http_status', None)
    api_code = getattr(exc, 'api_code', None)
    kind = allowed(getattr(exc, 'diagnostic_kind', None), KINDS)
    if kind == 'unknown':
        if type(http_status) is int and 100 <= http_status <= 599:
            kind = 'http_status'
        elif type(api_code) is int and -2147483648 <= api_code <= 2147483647:
            kind = 'api_code'
        else:
            kind = 'unexpected'
    return (f'stage={stage} category={kind}'
            + number_field('http_status', http_status, 100, 599)
            + number_field('api_code', api_code, -2147483648, 2147483647))
