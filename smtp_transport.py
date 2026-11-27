"""Classify SMTP failures conservatively at the send_message boundary."""
import smtplib
import ssl

from safe_diagnostics import SMTP_STAGES, KINDS, allowed, error_fields, error_kind, number_field


class SafeSMTPFailure(OSError):
    """Connection/setup failed before send_message was called; no mail submitted."""

    def __init__(self, message, *, stage=None, kind=None, smtp_status=None, os_errno=None):
        super().__init__(message)
        self.diagnostic_stage, self.diagnostic_kind = stage, kind
        self.smtp_status, self.os_errno = smtp_status, os_errno


def smtp_failure_fields(exc):
    if isinstance(exc, SafeSMTPFailure):
        return (f'stage={allowed(exc.diagnostic_stage, SMTP_STAGES)} '
                f'category={allowed(exc.diagnostic_kind, KINDS)}'
                + number_field('smtp_status', exc.smtp_status, 100, 599)
                + number_field('errno', exc.os_errno, 1, 65535))
    return error_fields(exc)


def transmit(msg, host, port, security, username=None, password=None):
    if security not in ('tls', 'starttls', 'none'):
        raise ValueError('Unsupported SMTP security mode')
    started = accepted = False
    stage = 'tls_context'
    try:
        context = ssl.create_default_context()
        stage = 'connect'
        if security == 'tls':
            connection = smtplib.SMTP_SSL(host, port, timeout=30, context=context)
        else:
            connection = smtplib.SMTP(host, port, timeout=30)
        with connection as client:
            if security == 'starttls':
                stage = 'ehlo'
                client.ehlo()
                stage = 'starttls'
                client.starttls(context=context)
                stage = 'ehlo'
                client.ehlo()
            if username:
                stage = 'auth'
                client.login(username, password)
            started = True
            refused = client.send_message(msg)
            if refused:
                raise RuntimeError('SMTP recipient refused')
            accepted = True
    except Exception as exc:
        if accepted:
            # DATA acceptance is decisive; a later QUIT failure cannot undo it.
            return
        if not started:
            raise SafeSMTPFailure('SMTP setup failed before message submission',
                                  stage=stage, kind=error_kind(exc),
                                  smtp_status=exc.smtp_code if isinstance(exc, smtplib.SMTPResponseException) else None,
                                  os_errno=exc.errno if isinstance(exc, OSError) else None) from None
        raise
