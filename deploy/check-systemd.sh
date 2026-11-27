#!/usr/bin/env bash
# Offline syntax verification only. Never install, enable or start a unit.
set -euo pipefail
umask 077
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/ucon-unit-check.XXXXXXXX")"
trap 'rm -rf -- "$WORK"' EXIT
unit="$ROOT/deploy/systemd/ucon-trailcam-smtp.service"
# The installed executable intentionally does not exist on the test host.
# Substitute only that executable for syntax verification; never execute it.
sed 's|^ExecStart=/opt/ucon-trailcam-smtp/current/venv/bin/ucon-trailcam-smtp |ExecStart=/usr/bin/true |' "$unit" > "$WORK/ucon-trailcam-smtp.service"
grep -q '^ExecStart=/usr/bin/true ' "$WORK/ucon-trailcam-smtp.service"
systemd-analyze verify --man=no "$WORK/ucon-trailcam-smtp.service"
echo "Offline systemd unit syntax check passed (placeholder executable only)."
