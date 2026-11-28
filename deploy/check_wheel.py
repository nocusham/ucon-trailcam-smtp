"""Validate a local project wheel against the committed runtime source."""
import argparse
from email.parser import BytesParser
from pathlib import Path
import zipfile


def check(wheel, source):
    package = 'ucon_trailcam_smtp'
    expected = {p.relative_to(source).as_posix(): p
                for p in (source / package).rglob('*.py')}
    if not expected:
        raise ValueError('No runtime source found')
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or archive.testzip() is not None:
            raise ValueError('Invalid wheel ZIP entries')
        metadata = [name for name in names if name.endswith('.dist-info/METADATA')]
        if len(metadata) != 1:
            raise ValueError('Expected exactly one wheel metadata directory')
        prefix = metadata[0].rsplit('/', 1)[0] + '/'
        allowed = {prefix + name for name in
                   ('METADATA', 'WHEEL', 'RECORD', 'entry_points.txt',
                    'top_level.txt', 'licenses/LICENSE', 'LICENSE')}
        actual = set(names) - allowed
        if actual != set(expected):
            raise ValueError('Wheel contains unexpected or missing files: ' +
                             repr(sorted(actual ^ set(expected))))
        for name, path in expected.items():
            if archive.read(name) != path.read_bytes():
                raise ValueError('Wheel runtime differs from source: ' + name)
        info = BytesParser().parsebytes(archive.read(metadata[0]))
        if info['Name'] != 'ucon-trailcam-smtp' or info['Version'] != '0.0.0.dev0':
            raise ValueError('Unexpected development wheel metadata')
        required = {prefix + name for name in ('WHEEL', 'RECORD', 'entry_points.txt')}
        if not required <= set(names):
            raise ValueError('Incomplete wheel metadata')
        if not {prefix + 'licenses/LICENSE', prefix + 'LICENSE'} & set(names):
            raise ValueError('Project license is missing')
        if b'ucon_trailcam_smtp.trailcam_service:main' not in archive.read(prefix + 'entry_points.txt'):
            raise ValueError('Missing service entrypoint')
    print(f'Wheel contents OK: {len(expected)} runtime Python files, project metadata and license only')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('wheel', type=Path)
    parser.add_argument('source', type=Path)
    args = parser.parse_args()
    check(args.wheel, args.source)


if __name__ == '__main__':
    main()
