"""Legacy checkout entrypoint for ucon_trailcam_smtp.camera_smtp."""
import sys
from _checkout import use_checkout_source

use_checkout_source()
from ucon_trailcam_smtp import camera_smtp as _impl

if __name__ == '__main__':
    raise SystemExit(_impl.main())

sys.modules[__name__] = _impl
