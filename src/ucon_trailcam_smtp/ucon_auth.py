"""Read Ucon credentials from a private file, environment or interactive prompts."""
import getpass
from ucon_trailcam_smtp.local_credentials import read_secret_values


def read_credentials(*, interactive=True):
    values = read_secret_values()
    account = values.get('UCON_ACCOUNT', '').strip()
    if not account and interactive:
        account = input('Ucon account: ').strip()
    password = values.get('UCON_PASSWORD', '')
    if not password and interactive:
        password = getpass.getpass('Ucon password: ')
    if not account or not password:
        raise ValueError('Account and password are required')
    return account, password
