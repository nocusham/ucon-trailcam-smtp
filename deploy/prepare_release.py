"""Prepare a local development release without activating it.

Only trusted local wheels and an operator-owned directory may be used.
Production privilege separation, state compatibility and backup gates are
not implemented here. This command deliberately refuses root execution.
"""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

from deploy.release_layout import ReleaseError, _release_id, _ready_release

PROJECT_WHEEL = 'ucon_trailcam_smtp-0.0.0.dev0-py3-none-any.whl'
HERE = Path(__file__).resolve().parent


def _owned_directory(path):
    path = Path(path).absolute()
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or path.resolve() != path
            or info.st_uid != os.geteuid() or info.st_mode & 0o022):
        raise ReleaseError('Expected a real operator-owned directory without group/world write access')
    return path


def _wheel_digest(wheel):
    wheel = Path(wheel).absolute()
    if wheel.name != PROJECT_WHEEL or not stat.S_ISREG(wheel.lstat().st_mode):
        raise ReleaseError('Expected the local development project wheel')
    with wheel.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


@contextmanager
def deployment_lock(root):
    fd = os.open(root / '.deployment.lock',
                 os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    with os.fdopen(fd, 'rb') as lock:
        info = os.fstat(lock.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                or info.st_mode & 0o077):
            raise ReleaseError('Invalid deployment lock')
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _pins(path):
    values = []
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if not re.fullmatch(r'[A-Za-z0-9_.-]+==[0-9][A-Za-z0-9.+!-]*', line):
            raise ReleaseError('Only exact package versions are accepted')
        values.append(line)
    if not values:
        raise ReleaseError('Empty reference requirements')
    return values


def _install_and_check(directory, wheel, wheelhouse, *, copy_interpreter=False):
    # Keep the execution environment free of inherited camera/SMTP credentials
    # and pip configuration. All installs use explicitly selected local wheels.
    env = {'PATH': os.defpath, 'HOME': str(directory),
           'LANG': 'C.UTF-8', 'PIP_CONFIG_FILE': os.devnull,
           'PIP_DISABLE_PIP_VERSION_CHECK': '1', 'PIP_NO_CACHE_DIR': '1',
           'PYTHONDONTWRITEBYTECODE': '1'}

    def run(*args):
        subprocess.run(args, cwd=directory, env=env, check=True)

    options = ('--copies',) if copy_interpreter else ()
    run(sys.executable, '-m', 'venv', *options, str(directory / 'venv'))
    python = str(directory / 'venv/bin/python')
    pip = (python, '-m', 'pip', 'install', '--no-index', '--no-deps',
           '--only-binary=:all:', '--find-links', str(wheelhouse))
    build_pins = _pins(HERE / 'requirements-build.txt')
    pip_pin, = [p for p in build_pins if p.startswith('pip==')]
    pins = _pins(HERE / 'requirements-reference.txt')
    run(*pip, pip_pin)
    run(*pip, *pins)
    run(*pip, str(wheel))
    run(python, '-m', 'pip', 'check')
    run(python, '-I', '-c', '''
from importlib import import_module, metadata
from pathlib import Path
import pkgutil
import sys
import ucon_trailcam_smtp as package
from ucon_trailcam_smtp.local_credentials import _default_secret_path

if not Path(package.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()):
    raise SystemExit('Package did not load from the staged environment')
if _default_secret_path() is not None:
    raise SystemExit('Installed package has an implicit credential path')
for pin in sys.argv[1:]:
    name, expected = pin.split('==')
    if metadata.version(name) != expected:
        raise SystemExit('Unexpected installed version: ' + name)
for module in pkgutil.iter_modules(package.__path__, package.__name__ + '.'):
    import_module(module.name)
print('Staged runtime imports and exact versions OK.')
''', pip_pin, *pins, 'ucon-trailcam-smtp==0.0.0.dev0')
    run(str(directory / 'venv/bin/ucon-trailcam-smtp'), '--help')


def prepare_release(root, release, wheel, sha256, wheelhouse):
    """Install a new release at its final path; never change current.

    A failed installation stays incomplete for operator inspection. It cannot
    be reused or selected. The caller trusts the local wheelhouse; the project
    digest checks identity, not authenticity or dependency artifact hashes.
    """
    root = _owned_directory(root)
    releases = _owned_directory(root / 'releases')
    release = _release_id(release)
    wheel = Path(wheel).absolute()
    wheelhouse = _owned_directory(wheelhouse)
    if (not isinstance(sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', sha256)
            or _wheel_digest(wheel) != sha256):
        raise ReleaseError('Project wheel SHA256 mismatch')
    with deployment_lock(root):
        directory = releases / release
        try:
            directory.mkdir(mode=0o700)
        except FileExistsError:
            raise ReleaseError('Release already exists; never overwrite an installation') from None
        _install_and_check(directory, wheel, wheelhouse)
        # Check the actual console entrypoint before publishing readiness.
        executable = directory / 'venv/bin/ucon-trailcam-smtp'
        if (not stat.S_ISREG(executable.lstat().st_mode)
                or not os.access(executable, os.X_OK)):
            raise ReleaseError('Missing executable console entrypoint')
        marker = directory / '.ready'
        # Publish a complete marker atomically, only after all checks.
        temporary = directory / '.ready.pending'
        try:
            with temporary.open('x', encoding='ascii') as stream:
                stream.write(release + '\n')
            os.replace(temporary, marker)
            _ready_release(root, release)
        except Exception:
            marker.unlink(missing_ok=True)
            raise
        return directory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--release', required=True)
    parser.add_argument('--wheel', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--wheelhouse', type=Path, required=True)
    args = parser.parse_args()
    if os.geteuid() == 0:
        parser.error('Development staging must not run as root')
    os.umask(0o077)
    try:
        prepare_release(args.root, args.release, args.wheel, args.sha256, args.wheelhouse)
    except (ReleaseError, OSError, subprocess.CalledProcessError) as exc:
        print(f'Release staging failed ({type(exc).__name__}); no activation performed.', file=sys.stderr)
        return 1
    print('Release prepared; current pointer and private state unchanged.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
