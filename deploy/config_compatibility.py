"""Offline configuration/credential check using the selected runtime parsers.

Run only as an unprivileged user in a trusted local environment. No network,
service startup, database writes or secret values in output. This does not
establish credential validity at the provider or recipient compatibility.
"""
import argparse
import os
from pathlib import Path
import sys

def check_config(config, secrets):
    from ucon_trailcam_smtp.camera_smtp import load_profiles
    from ucon_trailcam_smtp.health_alerts import load_alerts
    from ucon_trailcam_smtp.local_credentials import read_secret_values

    profiles = [profile for profile in load_profiles(config) if profile.enabled]
    if not profiles:
        raise ValueError('No enabled cameras')
    alerts = load_alerts(config)
    # Explicit private file, no inherited environment or implicit fallback.
    values = read_secret_values(environ={}, path=secrets)
    if not values.get('UCON_ACCOUNT', '').strip() or not values.get('UCON_PASSWORD', ''):
        raise ValueError('Missing cloud credentials')
    for profile in profiles:
        if profile.password_env and not values.get(profile.password_env):
            raise ValueError('Missing camera SMTP credential')
    if alerts.enabled and alerts.password_env and not values.get(alerts.password_env):
        raise ValueError('Missing alert SMTP credential')
    return {'enabled_cameras': len(profiles), 'alerts_enabled': alerts.enabled}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--secrets', required=True, type=Path)
    args = parser.parse_args()
    if os.geteuid() == 0:
        parser.error('Configuration check must not run as root')
    try:
        result = check_config(args.config, args.secrets)
    except Exception as exc:
        print(f'Configuration check failed ({type(exc).__name__}).', file=sys.stderr)
        return 1
    print(f"Offline configuration OK: enabled cameras={result['enabled_cameras']}; "
          f"alerts enabled={result['alerts_enabled']}.")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
