"""Compose fixed-unit maintenance and mixed-owner backup.

No CLI or activation. Caller must be a trusted administrator and exclude
concurrent administrators and all manual workers for the whole operation.
Compatibility and external writer exclusion remain explicit review hooks,
not automatic proofs. Only initialized installations are supported.
"""
import grp
import os
from pathlib import Path
import pwd

from deploy.prepare_release import deployment_lock
from deploy.production_backup import _directory, _locked_backup, _paths
from deploy.production_layout import APP, check_layout
from deploy.release_layout import (
    ReleaseError, _current_release, _ready_release, _release_id, switch_release,
)
from deploy.service_control import production_service_control
from deploy.state_backup import new_destination, verify_backup


def _coordinate(root, release, expected_previous, backup_id, administrator,
                service, control, confirm_no_other_writers, approve_compatibility):
    root = Path(root).absolute()
    if root.resolve() != root or (os.geteuid(), os.getegid()) != administrator:
        raise ReleaseError('Incorrect administrator context')
    release, previous, backup_id = map(_release_id, (release, expected_previous, backup_id))
    if release == previous:
        raise ReleaseError('Target is already the expected current release')
    install = root / 'opt' / APP
    for path in (root, root / 'opt', install, install / 'releases'):
        _directory(path, administrator, 0o755)
    with deployment_lock(install):
        _, _, backups, _ = _paths(root, administrator, service)
        destination = new_destination(backups / backup_id)
        _ready_release(install, release)
        if _current_release(install) != previous:
            raise ReleaseError('Current release changed since approval')
        if control.inhibit_start() is not True or control.quiesce() is not True:
            raise ReleaseError('Service stop failed')

        def require_stopped():
            if control.is_quiescent() is not True or confirm_no_other_writers() is not True:
                raise ReleaseError('All writers must be stopped')
        require_stopped()
        check_layout(root, release, *service, initialized=True)
        with _locked_backup(root, destination, administrator, service) as counts:
            manifest = verify_backup(destination)
            if approve_compatibility(previous, release, destination) is not True:
                raise ReleaseError('Compatibility approval required')
            if verify_backup(destination) != manifest:
                raise ReleaseError('Backup changed during approval')
            require_stopped()
            check_layout(root, release, *service, initialized=True)
            switch_release(install, release, expected_previous=previous)
            return {'previous': previous, 'selected': release, 'event_counts': counts}


def production_update(release, expected_previous, backup_id, unit_sha256, *,
                      confirm_no_other_writers, approve_compatibility):
    """Fixed host library for an approved update or code-only rollback.

    Service UID/GID are looked up from the dedicated account and group.
    Do not execute from a user-writable checkout. No automatic restart,
    marker recreation or DB restore even after success. Target acceptance,
    backup durability and actual compatibility policy remain open gates.
    """
    if (os.geteuid(), os.getegid()) != (0, 0):
        raise ReleaseError('Administrator identity required')
    account = pwd.getpwnam(APP)
    group = grp.getgrnam(APP)
    if account.pw_uid <= 0 or group.gr_gid <= 0 or account.pw_gid != group.gr_gid:
        raise ReleaseError('Unexpected service identity')
    control = production_service_control(unit_sha256)
    return _coordinate(Path('/'), release, expected_previous, backup_id, (0, 0),
                       (account.pw_uid, group.gr_gid), control,
                       confirm_no_other_writers, approve_compatibility)
