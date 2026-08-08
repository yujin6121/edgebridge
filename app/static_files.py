import os

from app.response import send_raw, send_text


log = None


def set_logger(logger):
    global log
    log = logger


def serve_file(server, path, content_type):
    try:
        with open(path, 'rb') as f:
            send_raw(server, 200, f.read(), content_type)
    except FileNotFoundError:
        send_text(server, 404, 'Not found')
    except Exception as e:
        if log:
            log.error(f'Dashboard file error: {e}')
        send_text(server, 500, 'Dashboard file error')


def serve_web(server, path_only, web_dir):
    if path_only in ('/web', '/web/'):
        serve_file(server, os.path.join(web_dir, 'index.html'), 'text/html; charset="utf-8"')
        return True

    prefix = '/web/assets/'
    if not path_only.startswith(prefix):
        return False

    rel_path = path_only[len(prefix):]
    abs_path = os.path.normpath(os.path.join(web_dir, 'assets', rel_path))
    if not abs_path.startswith(os.path.normpath(os.path.join(web_dir, 'assets'))):
        send_text(server, 400, 'Invalid asset path')
        return True
    if not os.path.isfile(abs_path):
        send_text(server, 404, 'Not found')
        return True

    content_types = {
        '.css': 'text/css; charset="utf-8"',
        '.js': 'application/javascript; charset="utf-8"',
        '.json': 'application/json; charset="utf-8"',
        '.svg': 'image/svg+xml',
        '.png': 'image/png',
    }
    ext = os.path.splitext(rel_path)[1].lower()
    serve_file(server, abs_path, content_types.get(ext, 'application/octet-stream'))
    return True
