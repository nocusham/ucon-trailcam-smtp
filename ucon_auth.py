"""Read Ucon credentials from the process environment or interactive prompts."""
import getpass
import os


def read_credentials():
    account = os.environ.get('UCON_ACCOUNT', '').strip()
    if not account:
        account = input('Ucon account: ').strip()
    password = os.environ.get('UCON_PASSWORD', '')
    if not password:
        password = getpass.getpass('Ucon password: ')
    if not account or not password:
        raise ValueError('Account and password are required')
    return account, password
