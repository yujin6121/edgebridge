import os
import socket
import uuid

from app import state
from app.persistence import data_path

try:
    from zeroconf import ServiceInfo, Zeroconf
    HAVE_ZEROCONF = True
except Exception:
    HAVE_ZEROCONF = False


def get_install_id():
    p = data_path('install_id')
    try:
        if os.path.exists(p):
            with open(p) as f:
                v = f.read().strip()
                if v:
                    return v
    except Exception:
        pass
    v = str(uuid.uuid4())
    try:
        with open(p, 'w') as f:
            f.write(v)
    except Exception:
        pass
    return v


def start_mdns(ip, port):
    if not state.MDNS_ENABLED:
        return
    if not HAVE_ZEROCONF:
        state.log.warn('mDNS requested but the "zeroconf" package is not installed -- skipping')
        return
    try:
        info = ServiceInfo(
            state.MDNS_TYPE,
            f'{state.MDNS_NAME}.{state.MDNS_TYPE}',
            addresses=[socket.inet_aton(ip)],
            port=port,
            properties={'install_id': get_install_id(), 'version': state.VERSION},
            server=f'{state.MDNS_NAME.replace(" ", "-")}.local.',
        )
        zc = Zeroconf()
        zc.register_service(info)
        state._zeroconf, state._mdns_info = zc, info
        state.log.hilite(f' > mDNS advertised as "{state.MDNS_NAME}" ({state.MDNS_TYPE}) at {ip}:{port}')
    except Exception as e:
        state.log.warn(f'mDNS registration failed (expected in Docker bridge mode; use host networking): {e}')


def stop_mdns():
    try:
        if state._zeroconf and state._mdns_info:
            state._zeroconf.unregister_service(state._mdns_info)
            state._zeroconf.close()
    except Exception:
        pass
    state._zeroconf = None
    state._mdns_info = None
