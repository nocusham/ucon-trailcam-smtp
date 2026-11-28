"""One sequential service cycle; callbacks isolate network and local operations."""
import sqlite3
from ucon_trailcam_smtp.safe_diagnostics import error_fields


async def run_cycle(profiles, *, cloud, devices, download, deliver, alerts,
                    download_enabled, emit=print):
    """Cloud failures never prevent delivery of already verified originals.

    A relay may only be opened after this cycle's successful cloud check,
    using the same authenticated device response. All relays close before mail.
    SQLite failures abort the cycle rather than trying another operation.
    """
    failed = False
    try:
        status = await cloud()
    except sqlite3.Error:
        raise
    except Exception as exc:
        emit(f'Cloud cycle stopped; stage=cloud_cycle {error_fields(exc)}.')
        status = 'error'
    failed |= status != 'ok'
    if download_enabled and status == 'ok':
        for p in profiles:
            try:
                failed |= bool(download(p, devices()))
            except sqlite3.Error:
                raise
            except Exception as exc:
                emit(f'Camera {p.name}: download stopped; stage=download {error_fields(exc)}.')
                failed = True
    elif download_enabled:
        emit('Cloud not ready; defer all camera downloads.')
    try:
        failed |= bool(alerts(status))
    except sqlite3.Error:
        raise
    except Exception as exc:
        emit(f'Alarm dispatch stopped; stage=alarm_dispatch {error_fields(exc)}.')
        failed = True
    try:
        failed |= bool(deliver(profiles))
    except sqlite3.Error:
        raise
    except Exception as exc:
        emit(f'Image delivery stopped; stage=delivery {error_fields(exc)}.')
        failed = True
    return int(failed)
