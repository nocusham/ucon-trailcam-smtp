"""Legacy checkout entrypoint for ucon_trailcam_smtp.trailcam_service."""
import sys
from _checkout import use_checkout_source

use_checkout_source()
from ucon_trailcam_smtp import trailcam_service as _impl

if __name__ == '__main__':
    raise SystemExit(_impl.main())

sys.modules[__name__] = _impl
