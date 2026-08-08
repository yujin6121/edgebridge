import time
import configparser
import os
from collections import OrderedDict
import ipaddress

import requests

from app import state
from app.mdns import start_mdns, stop_mdns
from app.persistence import configure as configure_persistence, now_ms
from app.app_logger import Logger
from app.response import set_logger as set_response_logger
from app.static_files import set_logger as set_static_logger
from app.validation import set_logger as set_validation_logger


def st_pat_valid():
    """True if a PAT is configured in edgebridge.cfg AND SmartThings accepts it
    (any response other than 401). Cached for state.ST_PAT_TTL seconds."""
    if not state.SMARTTHINGS_TOKEN:
        return False
    now = time.time()
    if (now - state._st_pat_checked_at) < state.ST_PAT_TTL:
        return state._st_pat_valid
    state._st_pat_checked_at = now
    try:
        r = requests.get('https://api.smartthings.com/v1/locations',
                         headers={'Authorization': state.SMARTTHINGS_TOKEN}, timeout=4)
        state._st_pat_valid = (r.status_code != 401)   # 401 = bad/expired token; 200/403 = token accepted
    except Exception as e:
        state.log.warn(f'PAT validity check failed: {e}')
        state._st_pat_valid = False
    return state._st_pat_valid


def build_ping():
    sessions = []
    connected = 0
    for s in state.aeb_sessions.values():
        session_state = s.get('state', 'CREATED')
        if session_state == 'CONNECTED':
            connected += 1
        sessions.append({'id': s['id'], 'state': session_state, 'lastError': s.get('lastError')})
    pat_ok = st_pat_valid()
    return {
        'battery': 100,
        'bridgeDevice': 'server',
        'bridgeVersion': state.DISPLAY_VERSION,
        'build': state.BUILD_SHA,
        'buildDate': state.BUILD_DATE,
        'serverStartTime': state.SERVER_START_STR,
        'supportedAiOptions': [],
        'stOauthConnected': pat_ok,
        'stTokenConfigured': bool(state.SMARTTHINGS_TOKEN),
        'stTokenValid': pat_ok,
        'accessTokenExpiresAt': None,
        'accessTokenMinutesLeft': None,
        'mqtt': {'total': len(state.aeb_sessions), 'connected': connected, 'sessions': sessions},
        'blocked': {'hosts': 0, 'attempts': 0},
    }


def build_dashboard_summary():
    ping = build_ping()
    registration_items = []
    for item in state.registrations:
        registration_items.append({
            'devaddr': ':'.join(str(x) for x in item.get('devaddr', []) if x is not None),
            'edgeid': item.get('edgeid'),
            'hubaddr': ':'.join(str(x) for x in item.get('hubaddr', []) if x is not None),
        })

    mqtt_sessions = []
    for session in state.aeb_sessions.values():
        mqtt_sessions.append({
            'id': session.get('id'),
            'state': session.get('state', 'CREATED'),
            'subscribedTopics': session.get('subscribedTopics', []),
            'forwardTarget': session.get('forwardTarget'),
            'pendingForwardCount': session.get('pendingForwardCount', 0),
            'lastConnectedTs': session.get('lastConnectedTs'),
            'lastForwardOkTs': session.get('lastForwardOkTs'),
            'lastError': session.get('lastError'),
            'effectiveClientId': session.get('effectiveClientId'),
        })

    return {
        'bridge': ping,
        'registrations': registration_items,
        'redirects': list(state.redirects.values()),
        'callbacks': list(state.callbacks.values()),
        'mqttSessions': mqtt_sessions,
        'server': {
            'version': state.VERSION,
            'dataDir': state.DATA_DIR,
            'serverPort': state.SERVER_PORT,
            'serverIp': state.SERVER_IP,
            'mdnsEnabled': state.MDNS_ENABLED,
            'mdnsName': state.MDNS_NAME,
        },
        'generatedAt': now_ms(),
    }


def current_settings_snapshot():
    token = state.SMARTTHINGS_TOKEN[7:] if state.SMARTTHINGS_TOKEN.startswith('Bearer ') else state.SMARTTHINGS_TOKEN
    return {
        'forwardingTimeout': state.FWTIMEOUT,
        'mdnsEnabled': state.MDNS_ENABLED,
        'mdnsName': state.MDNS_NAME,
        'stTokenConfigured': bool(token),
        'serverIp': state.SERVER_IP,
        'serverPort': state.SERVER_PORT,
        'timezone': state.TIMEZONE,
        'dataDir': state.DATA_DIR,
        'source': {
            'configFile': os.path.join(os.getcwd(), state.CONFIGFILENAME),
            'envOverrides': {
                'EB_ST_TOKEN': bool(os.environ.get('EB_ST_TOKEN', '').strip()),
                'EB_FW_TIMEOUT': bool(os.environ.get('EB_FW_TIMEOUT', '').strip()),
                'EB_MDNS_ENABLED': os.environ.get('EB_MDNS_ENABLED', '').strip().lower() in ('no', 'false', '0'),
                'EB_MDNS_NAME': bool(os.environ.get('EB_MDNS_NAME', '').strip()),
                'EB_TZ': bool(os.environ.get('EB_TZ', '').strip()),
            },
        },
    }


def read_existing_config_values():
    values = {}
    parser = configparser.ConfigParser()
    path = os.path.join(os.getcwd(), state.CONFIGFILENAME)
    if not parser.read(path):
        return values
    try:
        values['Server_IP'] = parser.get('config', 'Server_IP', fallback='')
        values['Server_Port'] = parser.get('config', 'Server_Port', fallback=str(state.DEFAULT_SERVERPORT))
        values['SmartThings_Bearer_Token'] = parser.get('config', 'SmartThings_Bearer_Token', fallback='')
        values['forwarding_timeout'] = parser.get('config', 'forwarding_timeout', fallback=str(state.FWTIMEOUT))
        values['console_output'] = parser.get('config', 'console_output', fallback='yes')
        values['logfile_output'] = parser.get('config', 'logfile_output', fallback='no')
        values['logfile'] = parser.get('config', 'logfile', fallback=state.LOGFILE)
        values['Data_Dir'] = parser.get('config', 'Data_Dir', fallback='')
        values['mDNS_enabled'] = parser.get('config', 'mDNS_enabled', fallback='yes')
        values['mDNS_name'] = parser.get('config', 'mDNS_name', fallback=state.MDNS_NAME)
        values['Timezone'] = parser.get('config', 'Timezone', fallback='UTC')
    except Exception:
        pass
    return values


def persist_config_file():
    path = os.path.join(os.getcwd(), state.CONFIGFILENAME)
    token = state.SMARTTHINGS_TOKEN[7:] if state.SMARTTHINGS_TOKEN.startswith('Bearer ') else state.SMARTTHINGS_TOKEN
    existing = read_existing_config_values()
    desired = OrderedDict([
        ('Server_IP', state.SERVER_IP or existing.get('Server_IP', '')),
        ('Server_Port', str(state.SERVER_PORT or existing.get('Server_Port', state.DEFAULT_SERVERPORT))),
        ('SmartThings_Bearer_Token', token),
        ('forwarding_timeout', str(state.FWTIMEOUT)),
        ('console_output', existing.get('console_output', 'yes')),
        ('logfile_output', existing.get('logfile_output', 'no')),
        ('logfile', existing.get('logfile', state.LOGFILE)),
        ('Data_Dir', existing.get('Data_Dir', '')),
        ('mDNS_enabled', 'yes' if state.MDNS_ENABLED else 'no'),
        ('mDNS_name', state.MDNS_NAME),
        ('Timezone', state.TIMEZONE),
    ])
    key_lookup = {key.lower(): key for key in desired}
    lines = []
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                lines = f.read().splitlines()
        except Exception as e:
            raise RuntimeError(f'Unable to read config file: {e}')
    if not lines:
        lines = ['[config]']

    out = []
    in_config = False
    seen = set()
    for line in lines:
        stripped = line.strip()
        lowered = stripped.lower()
        if lowered.startswith('[') and lowered.endswith(']'):
            if in_config and seen != set(desired):
                for key, value in desired.items():
                    if key not in seen:
                        out.append(f'{key} = {value}')
                        seen.add(key)
            in_config = lowered == '[config]'
            out.append(line)
            continue

        if in_config and '=' in line and not stripped.startswith('#') and not stripped.startswith(';'):
            key, _, _ = line.partition('=')
            lookup = key.strip().lower()
            if lookup in key_lookup:
                canonical = key_lookup[lookup]
                out.append(f'{canonical} = {desired[canonical]}')
                seen.add(canonical)
                continue
        out.append(line)

    if '[config]' not in [l.strip().lower() for l in lines]:
        out = ['[config]'] + [f'{key} = {value}' for key, value in desired.items()]
    else:
        for key, value in desired.items():
            if key not in seen:
                out.append(f'{key} = {value}')

    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(out) + '\n')
    except Exception as e:
        raise RuntimeError(f'Unable to write config file: {e}')


def apply_settings_updates(updates):
    settings_changed = {}
    mdns_prev = state.MDNS_ENABLED
    mdns_name_prev = state.MDNS_NAME

    if 'forwardingTimeout' in updates:
        try:
            fw = int(updates['forwardingTimeout'])
            if fw < 1:
                raise ValueError('forwardingTimeout must be >= 1')
            state.FWTIMEOUT = fw
            settings_changed['forwardingTimeout'] = state.FWTIMEOUT
        except Exception:
            raise ValueError('forwardingTimeout must be a positive integer')

    if 'mdnsEnabled' in updates:
        state.MDNS_ENABLED = bool(updates['mdnsEnabled'])
        settings_changed['mdnsEnabled'] = state.MDNS_ENABLED

    if 'mdnsName' in updates:
        name = str(updates['mdnsName']).strip()
        if not name:
            raise ValueError('mDNS name cannot be empty')
        state.MDNS_NAME = name
        settings_changed['mdnsName'] = state.MDNS_NAME

    token_in = str(updates.get('stToken', '')).strip().strip('"').strip("'").strip()
    if token_in:
        if len(token_in) != state.TOKEN_LENGTH:
            raise ValueError('SmartThings PAT must be 36 characters')
        state.SMARTTHINGS_TOKEN = f'Bearer {token_in}'
        settings_changed['stTokenConfigured'] = True

    persist_config_file()
    if state.MDNS_ENABLED != mdns_prev or state.MDNS_NAME != mdns_name_prev:
        stop_mdns()
        if state.MDNS_ENABLED and state.SERVER_ADVERTISED_IP:
            start_mdns(state.SERVER_ADVERTISED_IP, state.SERVER_PORT)
    return settings_changed


def process_config(config_filename):
    if not state.DATA_DIR:
        state.DATA_DIR = os.environ.get('EB_DATA_DIR', os.getcwd())

    state.SERVER_IP = ''
    state.SERVER_PORT = state.DEFAULT_SERVERPORT
    state.SMARTTHINGS_TOKEN = state.DEFAULT_ST_TOKEN
    conoutp = True
    logoutp = False
    logfile = ''

    parser = configparser.ConfigParser()
    if parser.read(os.path.join(os.getcwd(), config_filename)):
        try:
            config_ip = ipaddress.ip_address(parser.get('config', 'Server_IP'))
            state.SERVER_IP = str(config_ip)
        except Exception:
            pass

        try:
            config_port = int(parser.get('config', 'Server_Port'))
            if 0 < config_port <= state.MAXPORT:
                state.SERVER_PORT = config_port
            else:
                print(f'\033[31mInvalid port from config file; using default: {state.DEFAULT_SERVERPORT}\033[0m')
        except Exception:
            print(f'\033[31mMissing port from config file; using default: {state.DEFAULT_SERVERPORT}\033[0m')

        try:
            config_token = parser.get('config', 'SmartThings_Bearer_Token').strip().strip('"').strip("'").strip()
            if len(config_token) == state.TOKEN_LENGTH:
                state.SMARTTHINGS_TOKEN = 'Bearer ' + config_token
            elif config_token:
                print('\033[31mInvalid SmartThings Token from config file (expected 36 chars); assumed None\033[0m')
        except Exception:
            pass

        try:
            if parser.get('config', 'forwarding_timeout'):
                state.FWTIMEOUT = int(parser.get('config', 'forwarding_timeout'))
        except Exception:
            pass

        if not os.environ.get('EB_DATA_DIR'):
            try:
                d = parser.get('config', 'Data_Dir')
                if d:
                    state.DATA_DIR = d
            except Exception:
                pass

        try:
            if parser.get('config', 'mDNS_enabled').lower() in ('no', 'false', '0'):
                state.MDNS_ENABLED = False
        except Exception:
            pass
        try:
            name = parser.get('config', 'mDNS_name')
            if name:
                state.MDNS_NAME = name
        except Exception:
            pass

        try:
            conoutp = parser.get('config', 'console_output').lower() == 'yes'
            if parser.get('config', 'logfile_output').lower() == 'yes':
                logoutp = True
                logfile = parser.get('config', 'logfile')
            else:
                logoutp = False
                logfile = ''
        except Exception:
            print('Using output config defaults')

    env_token = os.environ.get('EB_ST_TOKEN', '').strip().strip('"').strip("'").strip()
    if env_token:
        state.SMARTTHINGS_TOKEN = 'Bearer ' + env_token
    env_port = os.environ.get('EB_SERVER_PORT', '').strip()
    if env_port:
        try:
            p = int(env_port)
            if 0 < p <= state.MAXPORT:
                state.SERVER_PORT = p
        except ValueError:
            pass
    env_ip = os.environ.get('EB_SERVER_IP', '').strip()
    if env_ip:
        state.SERVER_IP = env_ip
    env_fw = os.environ.get('EB_FW_TIMEOUT', '').strip()
    if env_fw:
        try:
            state.FWTIMEOUT = int(env_fw)
        except ValueError:
            pass
    try:
        config_tz = parser.get('config', 'Timezone').strip()
        if config_tz:
            state.TIMEZONE = config_tz
    except Exception:
        pass
    env_tz = os.environ.get('EB_TZ', '').strip()
    if env_tz:
        state.TIMEZONE = env_tz
    if os.environ.get('EB_MDNS_ENABLED', '').strip().lower() in ('no', 'false', '0'):
        state.MDNS_ENABLED = False
    env_mdns_name = os.environ.get('EB_MDNS_NAME', '').strip()
    if env_mdns_name:
        state.MDNS_NAME = env_mdns_name

    if not state.DATA_DIR:
        state.DATA_DIR = os.getcwd()
    os.makedirs(state.DATA_DIR, exist_ok=True)
    state.log = Logger(conoutp, logoutp, logfile, False, state.TIMEZONE)
    configure_persistence(state.DATA_DIR, state.log)
    set_response_logger(state.log)
    set_static_logger(state.log)
    set_validation_logger(state.log)
