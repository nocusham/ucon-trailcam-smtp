"""Read a private, literal KEY=value credential file without executing shell code."""
import os
import re
import stat
from pathlib import Path


class CredentialError(ValueError):
    pass


def _default_secret_path():
    """Only use an implicit .env in a source checkout, never in site-packages."""
    module = Path(__file__).resolve()
    if module.parent.name == 'ucon_trailcam_smtp' and module.parent.parent.name == 'src':
        root = module.parents[2]
        if (root / 'pyproject.toml').is_file():
            return root / '.env'
    return None


def read_secret_values(environ=None, *, path=None):
    """File values take precedence; missing keys fall back to process environment."""
    values = dict(os.environ if environ is None else environ)
    explicit = path is not None or bool(values.get('UCON_SECRETS_FILE'))
    selected = path if path is not None else values.get('UCON_SECRETS_FILE')
    if not explicit:
        selected = _default_secret_path()
    if selected is None:
        return values
    target = Path(selected)
    try:
        fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        if not explicit:
            return values
        raise CredentialError('Configured credential file does not exist') from None
    except OSError:
        raise CredentialError('Cannot safely open credential file') from None
    try:
        with os.fdopen(fd, 'rb') as source:
            info = os.fstat(source.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) not in (0o400, 0o600)):
                raise CredentialError('Credential file must be owned by the process user and have mode 400 or 600')
            data = source.read(65537)
        if len(data) > 65536:
            raise CredentialError('Credential file too large')
        content = data.decode('utf-8')
    except (OSError, UnicodeError):
        raise CredentialError('Cannot read credential file') from None
    seen = set()
    for line in content.split('\n'):
        line = line.removesuffix('\r')
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        key, sep, value = line.partition('=')
        if (not sep or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key)
                or key in seen or '\x00' in value or '\r' in value):
            raise CredentialError('Invalid or duplicate credential file entry')
        seen.add(key)
        values[key] = value
    return values
