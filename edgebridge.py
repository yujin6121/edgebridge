VERSION = '1.0.1_AEB'

import http.server
import time
import socket
import requests
import os
import platform
import json
from urllib.parse import unquote

from app import state
from app.config import apply_settings_updates, build_dashboard_summary, build_ping
from app.config import current_settings_snapshot, process_config
from app.mdns import start_mdns, stop_mdns
from app.mqtt import aeb_get_json_body, handle_aeb_routes, restore_mqtt_sessions
from app.persistence import data_path, load_jsonl, now_ms, save_jsonl
from app.response import http_response, send_json, send_raw, send_text
from app.static_files import serve_web
from app.validation import verify_addr, verify_id

# ====== HTTP/2 + TLS 1.3 client for /api/forward ======
# Mirrors AndroidEdgeBridge (OkHttp: HTTP/2 via ALPN, TLS 1.2/1.3 negotiated). Tesla's
# owner-api 403s authenticated requests unless the connection is HTTP/2 + TLS 1.3
# (see TeslaMate fixes #5390 / #5406, June 2026).
import ssl
try:
    import httpx
    HAVE_HTTPX = True
except Exception:
    HAVE_HTTPX = False
# ======================================================

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'web')

def build_headers(server, path):
    headers = {}
    # 'accept-encoding' is dropped so `requests` performs transparent gzip decompression
    # and we forward already-decompressed bytes (Content-Encoding must NOT be re-advertised).
    ignored = ['host', 'te', 'connection', 'accept-encoding', 'content-length']
    present = set()
    for key, value in server.headers.items():
        if key.lower() not in ignored:
            headers[key] = value
            present.add(key.lower())

    if 'api.smartthings.com' in path:
        if 'authorization' not in present and len(state.SMARTTHINGS_TOKEN) > 0:
            headers['Authorization'] = state.SMARTTHINGS_TOKEN

    headers['Host'] = path.split('//')[1].split('/')[0]

    # Browser-like fallbacks (added only if the caller didn't provide them) so that
    # WAF/CDN-protected APIs (Tesla, etc.) don't reject the request with 403.
    if 'user-agent' not in present:
        headers['User-Agent'] = state.BROWSER_UA
    if 'accept' not in present:
        headers['Accept'] = 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
    if 'accept-language' not in present:
        headers['Accept-Language'] = 'ko-KR,ko;q=0.9,en;q=0.8'

    if server.data_bytes:
        headers['Content-Length'] = str(len(server.data_bytes))
    return headers


state._fwd_clients = {}


def _forward_client(url):
    """HTTP/2 forward client. Force TLS 1.3 for Tesla (owner-api 403s authenticated
    requests otherwise -- TeslaMate #5390/#5406); other hosts negotiate TLS normally so
    TLS-1.2-only sites (e.g. some gov APIs) keep working."""
    force_tls13 = ('teslamotors.com' in url) or ('.tesla.com' in url)
    key = 'tls13' if force_tls13 else 'default'
    client = state._fwd_clients.get(key)
    if client is None:
        ctx = ssl.create_default_context()
        if force_tls13:
            ctx.minimum_version = ssl.TLSVersion.TLSv1_3
        client = httpx.Client(http2=True, verify=ctx, timeout=state.FWTIMEOUT,
                              follow_redirects=True, trust_env=False)
        state._fwd_clients[key] = client
    return client


def proc_forward(server, method, path, arg):
    if not arg.startswith('url='):
        state.log.error('Missing URL from forward command')
        http_response(server, 400, '')
        return

    url = path[path.index('url=') + 4:]
    state.log.info(f'Sending {method} to {url}')
    headers = build_headers(server, path)
    state.log.debug(f'Headers: {headers}')

    lc_method = method.lower()
    if lc_method not in ('post', 'put', 'get', 'delete', 'patch'):
        state.log.error(f'Unsupported forward method: {method}')
        http_response(server, 405, '')
        return

    try:
        if HAVE_HTTPX:
            # HTTP/2 + (Tesla:) TLS 1.3, like AndroidEdgeBridge's OkHttp. httpx sets Host/
            # Content-Length itself; pass our clean header set (Chrome UA, no sec-ch-ua).
            send_headers = {k: v for k, v in headers.items() if k.lower() not in ('host', 'content-length')}
            r = _forward_client(url).request(lc_method.upper(), url, headers=send_headers, content=server.data_bytes)
        else:
            r = getattr(requests, lc_method)(url, data=server.data_bytes, headers=headers, timeout=state.FWTIMEOUT)
    except Exception as e:
        state.log.error(f'Forward error: {e}')
        send_raw(server, 502, f'Bad Gateway: {e}'.encode('utf-8'), 'text/plain; charset="utf-8"')
        return

    # Forward the RAW upstream bytes with a byte-accurate Content-Length so that
    # multi-byte (Korean/CJK) bodies are not truncated, and pass the Content-Type through.
    ctype = r.headers.get('Content-Type', 'application/octet-stream')
    state.log.debug(f'Returned {r.status_code}, {len(r.content)} bytes')
    send_raw(server, r.status_code, r.content, ctype)
    if r.status_code == state.HTTP_OK:
        state.log.info(f'Response returned to Edge driver ({len(r.content)} bytes)')
    else:
        state.log.warn(f'HTTP {r.status_code} returned to Edge driver')


# =============================================================================
#  /api/redirect  (persistent path -> URL mapping + inbound auto-proxy)
# =============================================================================

def normalize_redirect_path(path):
    trimmed = path.strip()
    with_slash = trimmed if trimmed.startswith('/') else '/' + trimmed
    return (with_slash.rstrip('/') or '/').lower()


def find_redirect_match(request_path):
    lower = request_path.lower()
    best = None
    for reg in state.redirects.values():
        p = reg['path']
        if lower == p or lower.startswith(p + '/'):
            if best is None or len(p) > len(best['path']):
                best = reg
    return best


def query_param(server, name):
    q = server.path.split('?', 1)
    if len(q) != 2:
        return None
    for pair in q[1].split('&'):
        if pair.startswith(name + '='):
            return unquote(pair[len(name) + 1:])
    return None


def handle_redirect(server, method):
    if method == 'POST':
        path = query_param(server, 'path')
        target = query_param(server, 'target')
        if not path or not target:
            send_text(server, 400, 'Missing required parameters: path, target')
            return
        if not (target.lower().startswith('http://') or target.lower().startswith('https://')):
            send_text(server, 400, 'target must start with http:// or https://')
            return
        norm = normalize_redirect_path(path)
        state.redirects[norm] = {'path': norm, 'targetBase': target.rstrip('/'), 'createdAt': now_ms()}
        save_jsonl(state.REDIRECTSFILENAME, state.redirects)
        state.log.info(f'Redirect registered: {norm} -> {target}')
        send_text(server, 200, '')
    elif method == 'DELETE':
        path = query_param(server, 'path')
        if not path:
            send_text(server, 400, 'Missing required parameter: path')
            return
        state.redirects.pop(normalize_redirect_path(path), None)
        save_jsonl(state.REDIRECTSFILENAME, state.redirects)
        send_text(server, 200, '')
    elif method == 'GET':
        send_json(server, 200, list(state.redirects.values()))
    else:
        send_text(server, 405, '')


# =============================================================================
#  /api/callback  (store/retrieve arbitrary values by name key)
# =============================================================================

def handle_callback(server, method, parts):
    # parts == ['', 'api', 'callback', '{name}'?]
    if method == 'POST':
        name = query_param(server, 'name')
        if not name:
            send_text(server, 400, 'Missing required parameter: name')
            return
        if not state.CALLBACK_NAME_REGEX.match(name):
            send_text(server, 400, 'Invalid name (allowed: [A-Za-z0-9_-])')
            return
        value = server.data_bytes.decode('utf-8') if getattr(server, 'data_bytes', None) else ''
        if len(value.encode('utf-8')) > state.CALLBACK_MAX_VALUE_BYTES:
            send_text(server, 400, f'value too large (max {state.CALLBACK_MAX_VALUE_BYTES} bytes)')
            return
        state.callbacks[name] = {'name': name, 'value': value, 'createdAt': now_ms()}
        save_jsonl(state.CALLBACKSFILENAME, state.callbacks)
        state.log.info(f'Callback stored: {name}')
        send_text(server, 200, '')
    elif method == 'DELETE':
        name = query_param(server, 'name')
        if not name:
            send_text(server, 400, 'Missing required parameter: name')
            return
        state.callbacks.pop(name, None)
        save_jsonl(state.CALLBACKSFILENAME, state.callbacks)
        send_text(server, 200, '')
    elif method == 'GET':
        if len(parts) >= 4 and parts[3]:
            name = parts[3]
            entry = state.callbacks.get(name)
            if entry is None:
                send_text(server, 404, f'Not found: {name}')
                return
            send_text(server, 200, entry['value'])
        else:
            send_json(server, 200, list(state.callbacks.values()))
    else:
        send_text(server, 405, '')


# =============================================================================
#  Device -> Hub forwarding (original feature, unchanged)
# =============================================================================

def error_proc(hubaddr):
    key = f'{hubaddr[0]}:{hubaddr[1]}'
    if key in state.hubsenderrors:
        errcount = state.hubsenderrors[key] + 1
        if errcount == 3:
            del state.hubsenderrors[key]
            for item in state.registrations:
                if item['hubaddr'] == hubaddr:
                    state.regdeletelist.append(item)
        else:
            state.hubsenderrors[key] = errcount
    else:
        state.hubsenderrors[key] = 1


def passto_hub(server, regrecord):
    headers = {}
    hubaddr = regrecord['hubaddr'][0] + ':' + str(regrecord['hubaddr'][1])
    if regrecord['devaddr'][1] is not None:
        devaddr = regrecord['devaddr'][0] + ':' + str(regrecord['devaddr'][1])
    else:
        devaddr = regrecord['devaddr'][0]

    url = 'http://' + hubaddr + '/' + devaddr + '/' + server.command + server.path
    headers['Host'] = hubaddr
    if server.data_bytes and len(server.data_bytes) > 0:
        headers['Content-Length'] = str(len(server.data_bytes))
        if 'Content-Type' in server.headers:
            headers['Content-Type'] = server.headers['Content-Type']

    state.log.info(f'Sending POST: {url} to {hubaddr}')
    try:
        r = requests.post(url, headers=headers, data=server.data_bytes)
        if r.status_code == 200:
            state.log.info(f"Message forwarded to Edge ID {regrecord['edgeid']}")
        else:
            state.log.error(f"ERROR sending message to Edge hub {regrecord['hubaddr']}: {r.status_code}")
    except Exception:
        state.log.error(f"FAILED sending message to Edge hub {regrecord['hubaddr']}")
        error_proc(regrecord['hubaddr'])


def find_reg(reglist, devaddr, edgeid):
    for index in range(len(reglist)):
        if reglist[index]['devaddr'] == devaddr and reglist[index]['edgeid'] == edgeid:
            return index
    return None


def read_regs(regs_filename):
    file_path = data_path(regs_filename)
    try:
        with open(file_path, 'r') as f1:
            reglist = []
            for line in f1.readlines():
                reglist.append(json.loads(line))
            return reglist
    except Exception:
        state.log.warn('INFO: No existing registrations')
        return []


def write_regs(regs_filename, reglist):
    file_path = data_path(regs_filename)
    try:
        with open(file_path, 'w') as f1:
            for reg in reglist:
                f1.write(json.dumps(reg) + '\n')
    except Exception:
        state.log.error('Error saving registrations')


def proc_register(server, method, arglist):
    devaddr = hubaddr = edgeid = None
    for arg in arglist:
        if arg.startswith('devaddr='):
            devaddr = verify_addr(arg[8:])
        elif arg.startswith('hubaddr='):
            hubaddr = verify_addr(arg[8:])
        elif arg.startswith('edgeid='):
            edgeid = verify_id(arg[7:])
        else:
            state.log.error('Unrecognized argument in register command')
            http_response(server, 400, '')
            return

    if devaddr and hubaddr and edgeid:
        index = find_reg(state.registrations, devaddr, edgeid)
        if method in ['post', 'Post', 'POST']:
            state.log.info(f'Request to register device at {devaddr}')
            if index is None:
                state.registrations.append({'devaddr': devaddr, 'edgeid': edgeid, 'hubaddr': hubaddr})
                state.log.info('Registration record ADDED')
            else:
                state.registrations[index] = {'devaddr': devaddr, 'edgeid': edgeid, 'hubaddr': hubaddr}
                state.log.info('Existing registration was REPLACED')
            http_response(server, 200, '')
        elif method in ['delete', 'Delete', 'DELETE']:
            state.log.info(f'Request to remove registration {devaddr}')
            if index is not None:
                del state.registrations[index]
                state.log.info(f'Registration {index} DELETED')
                http_response(server, 200, '')
            else:
                state.log.warn(f'Request to remove address that is not registered: {devaddr}')
                http_response(server, 404, '')
        else:
            state.log.error(f'Invalid method provided ({method}) for register command')
            http_response(server, 405, '')
    else:
        state.log.error('Missing argument(s) in register command')
        http_response(server, 400, '')

    state.log.info(f'Updated registrations: {state.registrations}')
    write_regs(state.REGSFILENAME, state.registrations)


def proc_registered_requests(server):
    regfound = False
    for record in state.registrations:
        match = False
        if record['devaddr'][0] == server.client_address[0]:
            match = True
            if record['devaddr'][1] and record['devaddr'][1] != server.client_address[1]:
                match = False
            if match:
                regfound = True
                state.log.info('>>>>> Forwarding to SmartThings hub')
                passto_hub(server, record)

    if regfound:
        http_response(server, 200, '')
        for item in state.regdeletelist:
            state.log.info(f'Scrubbing registration record: {item}')
            state.registrations.remove(item)
        if len(state.regdeletelist) > 0:
            write_regs(state.REGSFILENAME, state.registrations)
            state.regdeletelist.clear()
        return True
    return False


# =============================================================================
#  Request dispatch
# =============================================================================

def handle_api(server):
    method = server.command
    path_only = server.path.split('?')[0]
    parts = path_only.split('/')   # ['', 'api', '<endpoint>', ...]
    endpoint = parts[2].lower() if len(parts) > 2 else ''

    if endpoint == 'forward':
        arg = server.path.split('?', 1)
        proc_forward(server, method, server.path, arg[1].split('&')[0] if len(arg) == 2 else '')
    elif endpoint == 'register':
        arg = server.path.split('?', 1)
        proc_register(server, method, arg[1].split('&') if len(arg) == 2 else [])
    elif endpoint == 'redirect':
        handle_redirect(server, method)
    elif endpoint == 'callback':
        handle_callback(server, method, parts)
    elif endpoint == 'ping':
        send_json(server, 200, build_ping())
    elif endpoint == 'dashboard':
        send_json(server, 200, build_dashboard_summary())
    elif endpoint == 'logs':
        send_json(server, 200, {'logs': state.log.buffer})
    elif endpoint == 'settings':
        if method == 'GET':
            send_json(server, 200, current_settings_snapshot())
            return
        if method in ('POST', 'PUT'):
            req = aeb_get_json_body(server)
            try:
                changed = apply_settings_updates(req)
                send_json(server, 200, {
                    'ok': True,
                    'settings': current_settings_snapshot(),
                    'changed': changed,
                })
            except ValueError as e:
                send_json(server, 400, {'error': {'code': 'BAD_SETTINGS', 'message': str(e)}})
            except Exception as e:
                state.log.error(f'Settings update failed: {e}')
                send_json(server, 500, {'error': {'code': 'SETTINGS_UPDATE_FAILED', 'message': str(e)}})
            return
        send_json(server, 405, {'error': {'code': 'METHOD_NOT_ALLOWED', 'message': 'Unsupported method'}})
        return
    elif endpoint == 'llm':
        # LLM endpoint intentionally NOT ported
        send_json(server, 404, {'error': {'code': 'NOT_SUPPORTED', 'message': 'LLM endpoint not available in edgebridge-aeb'}})
    else:
        state.log.warn(f'Invalid endpoint: {endpoint}')
        http_response(server, 404, '')


def proc_msg(server):
    state.log.info('**********************************************************************************')
    state.log.info(f'{server.command} request received from: {server.client_address}')
    state.log.debug(f'Endpoint: {server.path}')

    server.data_bytes = None
    if 'Content-Length' in server.headers:
        server.data_bytes = server.rfile.read(int(server.headers['Content-Length']))

    path_only = server.path.split('?')[0]

    # 0) Built-in web dashboard
    if server.command == 'GET' and serve_web(server, path_only, WEB_DIR):
        return

    # 1) MQTT bridge traffic
    if path_only.startswith('/mqtt/'):
        if handle_aeb_routes(server):
            return

    # 2) Management/forward API
    if path_only.startswith('/api/'):
        handle_api(server)
        return

    # 3) Inbound from a registered IOT device -> forward to hub
    if proc_registered_requests(server):
        return

    # 4) Inbound auto-proxy via redirect mapping (302)
    match = find_redirect_match(path_only)
    if match:
        suffix = path_only[len(match['path']):]
        query = server.path.split('?', 1)
        location = match['targetBase'].rstrip('/') + suffix
        if len(query) == 2 and query[1]:
            location += '?' + query[1]
        state.log.info(f'Redirect proxy: {path_only} -> {location}')
        server.send_response(302)
        server.send_header('Location', location)
        server.send_header('Server', 'edgeBridge')
        server.end_headers()
        return

    state.log.error('Unregistered address or Invalid endpoint')
    http_response(server, 400, '')


class myHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):

    def do_POST(self):
        if '/api/ping' in self.path:
            state.log.debug('Pingreq')
            send_json(self, 200, build_ping())
            return
        proc_msg(self)

    def do_PUT(self):
        proc_msg(self)

    def do_GET(self):
        if '/api/ping' in self.path:
            state.log.debug('Pingreq')
            send_json(self, 200, build_ping())
            return
        proc_msg(self)

    def do_DELETE(self):
        proc_msg(self)

    def do_PATCH(self):
        proc_msg(self)

    def log_message(self, format, *args):
        return


class ThreadingHTTPServer(http.server.ThreadingHTTPServer):
    # Threaded so a slow upstream forward / MQTT flush does not block other requests.
    daemon_threads = True
    allow_reuse_address = True


if __name__ == '__main__':
    if platform.system() == 'Windows':
        os.system('color')

    state.SERVER_STARTED_AT = int(time.time() * 1000)
    state.SERVER_START_STR = time.strftime('%m/%d %H:%M')

    process_config(state.CONFIGFILENAME)
    state.registrations = read_regs(state.REGSFILENAME)
    state.redirects = load_jsonl(state.REDIRECTSFILENAME, 'path')
    state.callbacks = load_jsonl(state.CALLBACKSFILENAME, 'name')
    restore_mqtt_sessions()

    try:
        httpd = ThreadingHTTPServer((state.SERVER_IP, state.SERVER_PORT), myHTTPRequestHandler)
    except OSError as error:
        state.log.error(f'ERROR: cannot initialize Server; {error}')
        state.log.warn(f'Invalid IP address or Port {state.SERVER_PORT} may be in use by another application\n')
        httpd = False

    if httpd:
        if state.SERVER_IP == '':
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            myip = s.getsockname()[0]
            s.close()
        else:
            myip = state.SERVER_IP
        state.SERVER_ADVERTISED_IP = myip

        state.log.hilite(f'Forwarding Bridge Server v{state.DISPLAY_VERSION} ({state.BUILD_DATE}) [edgebridge-aeb]')
        state.log.hilite(f' > Serving HTTP on {myip}:{state.SERVER_PORT}')
        state.log.hilite(f' > Data directory: {state.DATA_DIR}')
        state.log.hilite(f' > Loaded {len(state.redirects)} redirect(s), {len(state.callbacks)} callback(s)')

        start_mdns(myip, state.SERVER_PORT)

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            state.log.warn('INFO: Application interrupted by user...\n')
        finally:
            stop_mdns()
