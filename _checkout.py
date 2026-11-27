"""Source-checkout bootstrap for legacy launchers and development tools."""
from pathlib import Path
import sys


def use_checkout_source():
    source = str(Path(__file__).resolve().parent / 'src')
    if source not in sys.path:
        sys.path.insert(0, source)
