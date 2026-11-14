"""Single-user access protection for HTTPS deployments."""
import base64
import binascii
import os
import secrets
from urllib.parse import urlsplit

from fastapi.responses import JSONResponse

def public_mode():
    return os.getenv('HUB_PUBLIC_MODE', '0') == '1'

def validate_configuration():
    if public_mode():
        if not os.getenv('HUB_USERNAME') or len(os.getenv('HUB_PASSWORD', '')) < 16:
            raise RuntimeError('Public deployment requires HUB_USERNAME and HUB_PASSWORD (at least 16 characters)')
        if not allowed_public_hosts():
            raise RuntimeError('Public deployment requires HUB_ALLOWED_HOSTS or RENDER_EXTERNAL_HOSTNAME')

def allowed_public_hosts():
    names = os.getenv('HUB_ALLOWED_HOSTS', '').split(',')
    names.append(os.getenv('RENDER_EXTERNAL_HOSTNAME', ''))
    return {n.strip().lower() for n in names if n.strip() and '*' not in n}

async def protect(request, call_next):
    host = request.headers.get('host', '').split(':')[0].lower()
    if host not in {'localhost', '127.0.0.1', 'testserver'} | allowed_public_hosts():
        return JSONResponse({'detail': 'Invalid host header'}, status_code=400)
    if public_mode():
        # Health checks expose no user data and permit readiness probes.
        if request.url.path == '/healthz' and request.method in ('GET', 'HEAD'):
            return JSONResponse({'ok': True})
        valid = False
        try:
            scheme, token = request.headers.get('authorization', '').split(' ', 1)
            if scheme.lower() == 'basic':
                username, password = base64.b64decode(token, validate=True).decode('utf-8').split(':', 1)
                valid = secrets.compare_digest(username.encode(), os.getenv('HUB_USERNAME', '').encode()) & secrets.compare_digest(password.encode(), os.getenv('HUB_PASSWORD', '').encode())
        except (ValueError, UnicodeError, binascii.Error):
            pass
        if not valid:
            return JSONResponse({'detail': '请使用部署时设置的用户名和密码登录'}, status_code=401,
                                headers={'WWW-Authenticate': 'Basic realm="Intelligence Hub", charset="UTF-8"'})
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        origin = request.headers.get('origin')
        if origin:
            parsed = urlsplit(origin)
            if parsed.netloc.lower() != request.headers.get('host', '').lower() or parsed.scheme not in ('http', 'https'):
                return JSONResponse({'detail': '拒绝跨站写入请求'}, status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['Cache-Control'] = 'no-store'
    return response
