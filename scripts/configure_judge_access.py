"""Create private, opt-in app authentication using the same password as Caddy."""
import argparse
from getpass import getpass
import json
import os
from pathlib import Path
import re
import secrets
import tempfile

from app.judge_access import ITERATIONS, normalize_origin, password_hash


def configure(origin, username, password, output):
    origin = normalize_origin(origin)
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', username):
        raise ValueError('Use a simple username of 1–64 letters, numbers, underscores or hyphens')
    if not password or len(password) > 512:
        raise ValueError('Password must contain 1–512 characters')
    salt = secrets.token_hex(32)
    config = {'version': 1, 'origin': origin, 'username': username, 'iterations': ITERATIONS,
              'salt': salt, 'password_hash': password_hash(password, salt)}
    output = Path(output).expanduser().resolve()
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.judge-', dir=output.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            json.dump(config, handle)
            handle.write('\n')
        os.chmod(temporary, 0o600)
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin', required=True)
    parser.add_argument('--username', default='judges')
    parser.add_argument('--output', type=Path, default=Path.home()/'.config/netcontract/judge-access.json')
    args = parser.parse_args()
    password = getpass('Enter the SAME judge password configured in Caddy: ')
    if password != getpass('Confirm password: '):
        parser.error('Passwords do not match')
    try:
        output = configure(args.origin, args.username, password, args.output)
    except ValueError as exc:
        parser.error(str(exc))
    print(f'Saved private judge configuration: {output}')
    print('Enable it in the NetContract service using NETCONTRACT_JUDGE_CONFIG with this file path.')


if __name__ == '__main__':
    main()
