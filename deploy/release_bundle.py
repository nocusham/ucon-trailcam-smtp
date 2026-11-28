"""Build and verify a local, development-only release ZIP.

The caller supplies a trusted source archive of the stated commit and its
project wheel. The manifest checks consistency, not provenance or authenticity.
No dependency wheels, private state, live activation or publication.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import zipfile

from deploy.check_wheel import check as check_wheel
PROJECT_WHEEL = 'ucon_trailcam_smtp-0.0.0.dev0-py3-none-any.whl'


FILES = (
    'LICENSE',
    'CHANGELOG.md',
    'config/.env.example',
    'config/config.example.toml',
    'deploy/__init__.py',
    'deploy/config_compatibility.py',
    'deploy/schema_compatibility.py',
    'deploy/state_backup.py',
    'deploy/requirements-reference.txt',
    'deploy/requirements-build.txt',
)
README = 'deploy/RELEASE_README.md'
WHEEL = 'dist/' + PROJECT_WHEEL
MANIFEST = 'manifest.json'
PAYLOAD = frozenset((*FILES, 'README.md', WHEEL))
MAX_FILE = 16 * 1024 * 1024


def commit_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{40}', value):
        raise ValueError('Expected a full lowercase Git commit ID')
    return value


def read_regular(path):
    path = Path(path)
    if path.resolve() != path.absolute() or not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError('Expected a regular nonsymlink input')
    if path.stat().st_size > MAX_FILE:
        raise ValueError('Release input exceeds size limit')
    return path.read_bytes()


def fingerprint(data):
    return {'sha256': hashlib.sha256(data).hexdigest(), 'size': len(data)}


def write_entry(archive, name, data):
    entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    entry.create_system = 3
    entry.external_attr = (stat.S_IFREG | 0o644) << 16
    archive.writestr(entry, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def verify_bundle(bundle, expected_commit=None):
    if expected_commit is not None:
        commit_id(expected_commit)
    with zipfile.ZipFile(bundle) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if len(names) != len(set(names)) or set(names) != PAYLOAD | {MANIFEST}:
            raise ValueError('Unexpected, missing or duplicate bundle paths')
        for entry in entries:
            if (entry.create_system != 3 or entry.external_attr >> 16 != stat.S_IFREG | 0o644
                    or entry.file_size > MAX_FILE or entry.flag_bits & 1):
                raise ValueError('Unexpected bundle file attributes')
        manifest = json.loads(archive.read(MANIFEST))
        if (not isinstance(manifest, dict)
                or set(manifest) != {'format', 'status', 'source_commit', 'files'}
                or manifest['format'] != 1 or manifest['status'] != 'development-only'):
            raise ValueError('Unsupported bundle manifest')
        commit_id(manifest['source_commit'])
        if expected_commit is not None and manifest['source_commit'] != expected_commit:
            raise ValueError('Bundle source commit mismatch')
        actual = {name: fingerprint(archive.read(name)) for name in sorted(PAYLOAD)}
        if manifest['files'] != actual:
            raise ValueError('Bundle file digest mismatch')
    return manifest


def build_bundle(source, wheel, commit, destination):
    commit_id(commit)
    source, wheel, destination = map(lambda p: Path(p).absolute(), (source, wheel, destination))
    if wheel.name != PROJECT_WHEEL:
        raise ValueError('Unexpected project wheel name')
    wheel_bytes = read_regular(wheel)
    # Source is a trusted committed export, not a live working directory.
    package = source / 'src/ucon_trailcam_smtp'
    for path in package.rglob('*.py'):
        read_regular(path)
    check_wheel(wheel, source / 'src')
    payload = {name: read_regular(source / name) for name in FILES}
    payload['README.md'] = read_regular(source / README)
    payload[WHEEL] = wheel_bytes
    manifest = {'format': 1, 'status': 'development-only', 'source_commit': commit,
                'files': {name: fingerprint(value) for name, value in sorted(payload.items())}}
    if destination.exists() or destination.is_symlink():
        raise FileExistsError('Release bundle already exists')
    payload[MANIFEST] = (json.dumps(manifest, sort_keys=True, indent=2) + '\n').encode()
    # Publish only a complete verified ZIP. Link refuses replacement even if
    # the destination appears during the build. No power-loss guarantee.
    with tempfile.TemporaryDirectory(prefix='.bundle-', dir=destination.parent) as tmp:
        candidate = Path(tmp) / 'bundle.zip'
        with zipfile.ZipFile(candidate, 'x') as archive:
            for name, value in sorted(payload.items()):
                write_entry(archive, name, value)
        verify_bundle(candidate, commit)
        os.link(candidate, destination)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    build = sub.add_parser('build')
    for name in ('source', 'wheel', 'destination'):
        build.add_argument('--' + name, type=Path, required=True)
    build.add_argument('--commit', required=True)
    verify = sub.add_parser('verify')
    verify.add_argument('--bundle', type=Path, required=True)
    verify.add_argument('--commit', required=True)
    args = parser.parse_args()
    if args.command == 'build':
        result = build_bundle(args.source, args.wheel, args.commit, args.destination)
    else:
        result = verify_bundle(args.bundle, args.commit)
    print(f"Development bundle OK: {len(result['files'])} payload files; "
          f"source={result['source_commit'][:12]}; no dependency wheels.")


if __name__ == '__main__':
    main()
