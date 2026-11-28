"""Offline same-owner update/rollback transaction rehearsal.

No systemd commands, privileged CLI, schema migration, database restore,
activation or first-install initialization. Use only trusted disposable
directories and trusted callbacks. The caller must prevent all writers
and starts for the entire transaction; the queue flock excludes only
cooperating workers. The callbacks are not a production service adapter.
"""
from pathlib import Path

from deploy.prepare_release import _owned_directory, deployment_lock
from deploy.release_layout import (
    ReleaseError, _current_release, _ready_release, _release_id, switch_release,
)
from deploy.state_backup import disjoint, locked_backup, new_destination, verify_backup


def _disabled(config):
    try:
        (config / 'service-enabled').lstat()
    except FileNotFoundError:
        return
    raise ReleaseError('Activation marker must be absent')


def _require_quiescence(config, is_quiescent):
    _disabled(config)
    if is_quiescent() is not True:
        raise ReleaseError('All writers must be stopped')


def coordinate_switch(root, config, state, destination, release, *,
                      expected_previous, quiesce, is_quiescent, approve_compatibility):
    """Switch a ready code release with a new verified backup of current state.

    Development-only same-owner rehearsal. No first-install path: the
    previous release and initialized queue must exist. Quiesce and
    is_quiescent are trusted caller hooks; approval must be read-only and
    evaluate the specific prior/target releases and the backup snapshot.
    All must return exactly True on success. No automatic service restart.
    The caller must use the same deployment lock for other admin actions.
    """
    root, config, state = map(_owned_directory, (root, config, state))
    destination = new_destination(destination)
    disjoint(root, config, state, destination)
    release = _release_id(release)
    previous = _release_id(expected_previous)
    if previous == release:
        raise ReleaseError('Target is already the expected current release')
    with deployment_lock(root):
        _disabled(config)
        _owned_directory(root / 'releases')
        _ready_release(root, release)
        if _current_release(root) != previous:
            raise ReleaseError('Current release changed since approval')
        if quiesce() is not True:
            raise ReleaseError('Writer stop failed')
        _require_quiescence(config, is_quiescent)
        with locked_backup(config, state, destination) as counts:
            manifest = verify_backup(destination)
            if approve_compatibility(previous, release, destination) is not True:
                raise ReleaseError('Compatibility approval required')
            if verify_backup(destination) != manifest:
                raise ReleaseError('Backup changed during approval')
            _require_quiescence(config, is_quiescent)
            # The existing pointer lock now also checks the expected old ID.
            # No DB or media changes occur as part of pointer selection.
            switch_release(root, release, expected_previous=previous)
            return {'previous': previous, 'selected': release, 'event_counts': counts}
