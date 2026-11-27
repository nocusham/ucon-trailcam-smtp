"""Compatibility entrypoint for tools.cloud_probe; implementation lives in tools/."""
import sys
from tools import cloud_probe as _impl

if __name__ == '__main__':
    raise SystemExit(_impl.main())

# Preserve legacy helper imports and mock targets without copying the module.
sys.modules[__name__] = _impl
