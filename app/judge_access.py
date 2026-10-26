"""Opt-in HTTPS judge access, verified independently of reverse-proxy headers."""
import base64
import binascii
import hashlib
import hmac
from ipaddress import ip_address
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

ITERATIONS = 600_000
CONFIG_ENV = 'NETCONTRACT_JUDGE_CONFIG'
CHALLENGE = {'WWW-Authenticate': 'Basic realm="NetContract judges", charset="UTF-8"',
             'Cache-Control': 'no-store'}


def normalize_origin(value):
    origin = urlsplit(value)
    if (origin.scheme != 'https' or not origin.hostname or origin.username or origin.password
            or origin.path not in {'', '/'} or origin.query or origin.fragment):
        raise ValueError('Judge origin must be one HTTPS origin without a path or credentials')
    # Accessing port validates malformed port values too.
    port = origin.port
    return f'https://{origin.hostname.lower()}' + (f':{port}' if port and port != 443 else '')


def local_request(request):
    try:
        return (request.url.hostname in {'localhost', '127.0.0.1', '::1'}
                and ip_address(request.client.host).is_loopback)
    except (ValueError, AttributeError):
        return False


def hosted_request(request):
    # Only middleware sets this state after verifying the password and HTTPS origin.
    return getattr(request.state, 'judge_origin', None) == f'{request.url.scheme}://{request.url.netloc}'


def load_config(path):
    config = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(config, dict):
        raise ValueError('Invalid judge configuration')
    if (config.get('version') != 1 or config.get('iterations') != ITERATIONS
            or normalize_origin(config['origin']) != config['origin']
            or not isinstance(config['username'], str) or not config['username']
            or len(bytes.fromhex(config['salt'])) != 32
            or len(bytes.fromhex(config['password_hash'])) != 32):
        raise ValueError('Invalid judge configuration')
    return config


def password_hash(password, salt):
    return hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(salt), ITERATIONS).hex()


def valid_credentials(header, config):
    if not header or len(header) > 4096:
        return False
    try:
        scheme, encoded = header.split(' ', 1)
        if scheme.lower() != 'basic':
            return False
        username, password = base64.b64decode(encoded, validate=True).decode('utf-8').split(':', 1)
        if len(password) > 512:
            return False
        matched_password = hmac.compare_digest(password_hash(password, config['salt']), config['password_hash'])
        return hmac.compare_digest(username.encode('utf-8'), config['username'].encode('utf-8')) and matched_password
    except (ValueError, UnicodeError, binascii.Error):
        return False


async def judge_access(request, call_next):
    request.state.judge_origin = None
    path = os.environ.get(CONFIG_ENV)
    if not path:
        return await call_next(request)
    # Retain engineer access via the local SSH tunnel.
    if local_request(request):
        return await call_next(request)
    try:
        config = load_config(path)
    except (OSError, ValueError, KeyError, TypeError):
        return JSONResponse({'detail': 'Hosted judge access is not configured correctly'}, status_code=503)
    if f'{request.url.scheme}://{request.url.netloc}' != config['origin']:
        return JSONResponse({'detail': 'Use the configured HTTPS judge address'}, status_code=403)
    if not await run_in_threadpool(valid_credentials, request.headers.get('authorization'), config):
        return JSONResponse({'detail': 'Judge login required'}, status_code=401, headers=CHALLENGE)
    # Browser Basic credentials are ambient; require a same-origin browser mutation.
    if request.method not in {'GET', 'HEAD', 'OPTIONS'} and request.headers.get('origin') != config['origin']:
        return JSONResponse({'detail': 'Requests must come from the judge site'}, status_code=403)
    request.state.judge_origin = config['origin']
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    return response
