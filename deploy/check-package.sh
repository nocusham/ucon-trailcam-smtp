#!/usr/bin/env bash
# Local development verification only. Never install into the reference venv.
set -euo pipefail
umask 077

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
REF_PY="${1:?Usage: bash deploy/check-package.sh /path/to/reference/python}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/ucon-package-check.XXXXXXXX")"
trap 'rm -rf -- "$WORK"' EXIT
export PYTHONDONTWRITEBYTECODE=1
export PIP_DISABLE_PIP_VERSION_CHECK=1
export PIP_NO_CACHE_DIR=1
unset PYTHONPATH PYTHONHOME

echo "=== Committed source ==="
git -C "$ROOT" rev-parse --short HEAD
mkdir "$WORK/source" "$WORK/wheels" "$WORK/empty"
git -C "$ROOT" archive HEAD | tar -xf - -C "$WORK/source"
SOURCE="$WORK/source"

echo "=== Separate Python environment ==="
"$REF_PY" -m venv "$WORK/venv"
PY="$WORK/venv/bin/python"
"$PY" -c 'import sys, platform; assert sys.prefix != sys.base_prefix; print(sys.version.split()[0], platform.machine())'
"$PY" -m pip install -r "$SOURCE/deploy/requirements-build.txt"
"$PY" -m pip install -r "$SOURCE/deploy/requirements-reference.txt"
"$PY" -m pip check

echo "=== Exact reference versions ==="
"$PY" - "$SOURCE/deploy/requirements-reference.txt" "$SOURCE/deploy/requirements-build.txt" <<'PYTHON'
from importlib.metadata import version
from pathlib import Path
import sys

for filename in sys.argv[1:]:
    for line in Path(filename).read_text(encoding='utf-8').splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        name, expected = line.split('==')
        actual = version(name)
        if actual != expected:
            raise SystemExit(f'Unexpected version: {name}={actual}; expected {expected}')
print('All reference versions match.')
PYTHON

echo "=== Build and inspect development wheel ==="
"$PY" -m pip wheel --no-deps --no-build-isolation --wheel-dir "$WORK/wheels" "$SOURCE"
shopt -s nullglob
wheels=("$WORK/wheels/"*.whl)
[[ "${#wheels[@]}" -eq 1 ]]
"$PY" "$SOURCE/deploy/check_wheel.py" "${wheels[0]}" "$SOURCE/src"

echo "=== Install only the project wheel ==="
"$PY" -m pip install --no-deps "${wheels[0]}"
"$PY" -m pip check

echo "=== Installed package smoke test outside checkout ==="
(
    cd "$WORK/empty"
    "$PY" -I - <<'PYTHON'
from importlib import import_module, metadata
from pathlib import Path
import pkgutil
import sys
import ucon_trailcam_smtp as package
from ucon_trailcam_smtp.local_credentials import _default_secret_path

path = Path(package.__file__).resolve()
if not path.is_relative_to(Path(sys.prefix).resolve()) or 'site-packages' not in path.parts:
    raise SystemExit('Runtime was not imported from the isolated installation')
if _default_secret_path() is not None:
    raise SystemExit('Installed runtime must not search an implicit .env')
if metadata.version('ucon-trailcam-smtp') != '0.0.0.dev0':
    raise SystemExit('Unexpected installed project version')
modules = list(pkgutil.iter_modules(package.__path__, package.__name__ + '.'))
for module in modules:
    import_module(module.name)
print(f'Installed package imports OK: {len(modules)} modules')
PYTHON
    "$WORK/venv/bin/ucon-trailcam-smtp" --help > "$WORK/help.txt"
    grep -q -- '--queue-db' "$WORK/help.txt"
    grep -q -- '--config' "$WORK/help.txt"
    echo "Installed console command OK"
)

echo "=== Prepare independent versioned release from local wheels ==="
mkdir "$WORK/wheelhouse" "$WORK/install-root" "$WORK/install-root/releases"
"$PY" -m pip wheel --no-deps --wheel-dir "$WORK/wheelhouse" \
    -r "$SOURCE/deploy/requirements-reference.txt" -r "$SOURCE/deploy/requirements-build.txt"
digest=$(sha256sum "${wheels[0]}" | cut -d' ' -f1)
(
    cd "$SOURCE"
    "$PY" -m deploy.prepare_release --root "$WORK/install-root" \
        --release dev-check --wheel "${wheels[0]}" --sha256 "$digest" \
        --wheelhouse "$WORK/wheelhouse"
)
[[ -f "$WORK/install-root/releases/dev-check/.ready" ]]
[[ ! -e "$WORK/install-root/current" && ! -L "$WORK/install-root/current" ]]
echo "Versioned release staged without activation."
PY="$WORK/install-root/releases/dev-check/venv/bin/python"

echo "=== Full source regression using freshly installed dependencies ==="
(
    cd "$SOURCE"
    "$PY" -m unittest discover -s tests -t . -v
)
echo "Package and versioned staging checks passed."
