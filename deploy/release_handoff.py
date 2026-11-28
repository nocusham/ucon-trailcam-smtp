"""Prepare and copy a production candidate without selecting or activating it.

Only a trusted administrator may call the privileged handoff library, from
administrator-controlled code, with approved inputs and a stopped, isolated
builder. This is not a sandbox for hostile input. No root CLI is provided.
"""
import argparse
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile

from deploy.prepare_release import (
    _install_and_check, _owned_directory, _wheel_digest, deployment_lock,
)
from deploy.release_layout import ReleaseError, _current_release, _release_id


def build_candidate(directory, wheel, sha256, wheelhouse):
    """Build at the final path as a non-root, dedicated build identity."""
    if os.geteuid() == 0:
        raise ReleaseError('Candidate build must not run as root')
    directory = _owned_directory(directory)
    wheel = Path(wheel).absolute()
    wheelhouse = _owned_directory(wheelhouse)
    if any(directory.iterdir()):
        raise ReleaseError('Candidate directory must be empty')
    if (not isinstance(sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', sha256)
            or _wheel_digest(wheel) != sha256):
        raise ReleaseError('Project wheel SHA256 mismatch')
    _install_and_check(directory, wheel, wheelhouse, copy_interpreter=True)
    # No readiness marker. The administrator must accept the copied tree and
    # run independent service-user checks before marking it ready.


def _check_node(path, owner, device):
    info = path.lstat()
    if (info.st_uid, info.st_gid) != owner or info.st_dev != device:
        raise ReleaseError('Unexpected source ownership or filesystem')
    if os.listxattr(path, follow_symlinks=False):
        raise ReleaseError('Unexpected source extended attributes')
    if not stat.S_ISLNK(info.st_mode):
        if info.st_mode & (0o7000 | 0o022):
            raise ReleaseError('Unsafe source mode')
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise ReleaseError('Hardlinked source file')
    return info


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _copy_file(source, target, info):
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as reader:
        if _identity(os.fstat(reader.fileno())) != _identity(info):
            raise ReleaseError('Source changed before copying')
        out = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(out, 'wb') as writer:
            shutil.copyfileobj(reader, writer)
            writer.flush()
            os.fchmod(writer.fileno(), 0o755 if info.st_mode & stat.S_IXUSR else 0o644)
        if _identity(os.fstat(reader.fileno())) != _identity(info):
            raise ReleaseError('Source changed while copying')


def _copy_tree(source, target, owner):
    """Copy new inodes, normalizing modes; never execute the source tree."""
    device = source.lstat().st_dev
    def walk(src, dst, relative):
        info = _check_node(src, owner, device)
        if stat.S_ISDIR(info.st_mode):
            dst.mkdir(mode=0o700)
            for child in sorted(src.iterdir()):
                walk(child, dst / child.name, relative / child.name)
            if _identity(src.lstat()) != _identity(info):
                raise ReleaseError('Source directory changed during copying')
            dst.chmod(0o755)
        elif stat.S_ISREG(info.st_mode):
            _copy_file(src, dst, info)
        elif stat.S_ISLNK(info.st_mode):
            # CPython on Linux may generate this one relative link even with
            # --copies. All interpreter and dependency links are refused.
            if relative.as_posix() != 'venv/lib64' or os.readlink(src) != 'lib':
                raise ReleaseError('Unexpected source symlink')
            if _identity(src.lstat()) != _identity(info):
                raise ReleaseError('Source symlink changed')
            dst.symlink_to('lib')
        else:
            raise ReleaseError('Unexpected source file type')
    walk(source, target, Path('.'))


def _inspect_candidate(directory):
    if {p.name for p in directory.iterdir()} != {'venv'}:
        raise ReleaseError('Candidate must contain only venv, with no readiness marker')
    for path in (directory / 'venv', directory / 'venv/bin', directory / 'venv/lib'):
        if not stat.S_ISDIR(path.lstat().st_mode):
            raise ReleaseError('Candidate venv directories must be real directories')
    for name in ('python', 'ucon-trailcam-smtp'):
        path = directory / 'venv/bin' / name
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or not info.st_mode & stat.S_IXUSR:
            raise ReleaseError('Candidate must contain copied executable entrypoints')
    if not stat.S_ISREG((directory / 'venv/pyvenv.cfg').lstat().st_mode):
        raise ReleaseError('Missing regular venv configuration')


def _admin_directory(path, owner):
    info = path.lstat()
    if (path.resolve() != path or not stat.S_ISDIR(info.st_mode)
            or (info.st_uid, info.st_gid) != owner
            or info.st_mode & (0o7000 | 0o022)
            or os.listxattr(path, follow_symlinks=False)):
        raise ReleaseError('Expected trusted administrator-controlled directory')


def _handoff(root, release, builder, admin):
    """Filesystem primitive, also used by the same-owner local rehearsal.

    Caller must have exclusive control of the parent paths, must prevent
    builder execution and other writers throughout, and must establish
    trusted artifact identity separately. No .ready is created here.
    """
    root = Path(root).absolute()
    release = _release_id(release)
    if (os.geteuid(), os.getegid()) != admin:
        raise ReleaseError('Incorrect handoff identity')
    releases = root / 'releases'
    _admin_directory(root, admin)
    _admin_directory(releases, admin)
    with deployment_lock(root):
        if _current_release(root) == release:
            raise ReleaseError('Cannot replace the selected release')
        source = releases / release
        if not stat.S_ISDIR(source.lstat().st_mode):
            raise ReleaseError('Expected a real candidate directory')
        _check_node(source, builder, source.lstat().st_dev)
        _inspect_candidate(source)
        # Make fresh files in a private administrator directory on the same
        # filesystem. Keep the original for operator inspection, never
        # recursively delete a builder-controlled directory as root.
        work = Path(tempfile.mkdtemp(prefix='.handoff-', dir=releases))
        copied = work / 'copy'
        original = work / 'original'
        _copy_tree(source, copied, builder)
        _inspect_candidate(copied)
        os.rename(source, original)
        try:
            os.rename(copied, source)
        except OSError:
            # Restore the original location if possible. On failure leave
            # everything quarantined, without any readiness marker.
            os.rename(original, source)
            raise
        return original


def handoff_candidate(root, release, builder_uid, builder_gid):
    """Root-only library operation; no command-line privileged entrypoint.

    The isolated builder must have exited and all its processes must be
    stopped before the caller enters this function. The administrator must
    use a trusted local copy of this module, not execute a builder checkout.
    The return value is the quarantined original, not a ready release.
    """
    if (os.geteuid(), os.getegid()) != (0, 0):
        raise ReleaseError('Administrator identity required')
    if (type(builder_uid) is not int or type(builder_gid) is not int
            or builder_uid <= 0 or builder_gid <= 0):
        raise ReleaseError('Builder must be a non-root identity')
    return _handoff(root, release, (builder_uid, builder_gid), (0, 0))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', required=True, type=Path)
    parser.add_argument('--wheel', required=True, type=Path)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--wheelhouse', required=True, type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    build_candidate(args.directory, args.wheel, args.sha256, args.wheelhouse)
    print('Candidate built without readiness marker or activation.')


if __name__ == '__main__':
    main()
