"""Legacy checkout entrypoint for ucon_trailcam_smtp.cloud_intake."""
import sys
from _checkout import use_checkout_source

use_checkout_source()
from ucon_trailcam_smtp import cloud_intake as _impl

if __name__ == '__main__':
    raise SystemExit(_impl.main())

sys.modules[__name__] = _impl
