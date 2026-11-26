"""Classify SMTP failures conservatively at the send_message boundary."""
import smtplib
import ssl


class SafeSMTPFailure(OSError):
    """Connection/setup failed before send_message was called; no mail submitted."""


def transmit(msg, host, port, security, username=None, password=None):
    if security not in ('tls', 'starttls', 'none'):
        raise ValueError('Unsupported SMTP security mode')
    started = accepted = False
    try:
        context = ssl.create_default_context()
        if security == 'tls':
            connection = smtplib.SMTP_SSL(host, port, timeout=30, context=context)
        else:
            connection = smtplib.SMTP(host, port, timeout=30)
        with connection as client:
            if security == 'starttls':
                client.ehlo()
                client.starttls(context=context)
                client.ehlo()
            if username:
                client.login(username, password)
            started = True
            refused = client.send_message(msg)
            if refused:
                raise RuntimeError('SMTP recipient refused')
            accepted = True
    except Exception:
        if accepted:
            # DATA acceptance is decisive; a later QUIT failure cannot undo it.
            return
        if not started:
            raise SafeSMTPFailure('SMTP setup failed before message submission') from None
        raise
