import datetime
import json


log = None


def set_logger(logger):
    global log
    log = logger


def _debug(message):
    if log:
        log.debug(message)


def _error(message):
    if log:
        log.error(message)


def _send(server, code, body_bytes, content_type):
    try:
        server.send_response(code)
        if body_bytes:
            server.send_header('Content-Type', content_type)
            server.send_header('Content-Length', str(len(body_bytes)))
        server.send_header('Date', datetime.datetime.now(datetime.timezone.utc).strftime('%a, %d %b %Y %H:%M:%S GMT'))
        server.send_header('Server', 'edgeBridge')
        server.end_headers()
        if body_bytes:
            server.wfile.write(body_bytes)
        _debug('Response sent')
    except Exception as e:
        _error(f'HTTP Send error: {e}')


def http_response(server, code, responsetosend):
    # Content-Length is the UTF-8 byte length, not the Python character count.
    _send(server, code, responsetosend.encode('utf-8') if responsetosend else b'',
          'text/xml; charset="utf-8"')


def send_json(server, code, data):
    _send(server, code, json.dumps(data).encode('utf-8'), 'application/json; charset="utf-8"')


def send_text(server, code, text):
    _send(server, code, text.encode('utf-8') if text else b'', 'text/plain; charset="utf-8"')


def send_raw(server, code, body_bytes, content_type):
    _send(server, code, body_bytes or b'', content_type or 'application/octet-stream')
