"""Fail-closed selection of a configured Ucon camera by its stable UID."""


class SelectionError(ValueError):
    pass


def select_device(devices, index=0, *, uid=None):
    if not isinstance(devices, list):
        raise SelectionError('Device discovery: invalid list')
    if uid is not None:
        matches = [d for d in devices if isinstance(d, dict) and d.get('device_uid') == uid]
        if len(matches) != 1:
            raise SelectionError('Configured camera UID missing or ambiguous in account')
        device = matches[0]
    else:
        if not 0 <= index < len(devices):
            raise SelectionError('Device discovery: index unavailable')
        device = devices[index]
    actual = device.get('device_uid') if isinstance(device, dict) else None
    if not isinstance(actual, str) or not actual:
        raise SelectionError('Device discovery: missing selected device identifier')
    return device


def profile_uid(profiles, name):
    matches = [p for p in profiles if p.name == name and p.enabled]
    if len(matches) != 1:
        raise SelectionError('Configured camera missing or disabled')
    return matches[0].uid


def relay_credentials(device):
    password = device.get('device_pwd')
    if not isinstance(password, str) or not password:
        raise SelectionError('Selected camera has no relay credentials')
    name = device.get('device_name', '')
    return device['device_uid'], password, name if isinstance(name, str) else ''
