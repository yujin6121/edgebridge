import os
import re
import time

VERSION = '1.0.1_AEB'

log = None

SERVER_PORT = 8088
SERVER_IP = ''
SMARTTHINGS_TOKEN = ''
FWTIMEOUT = 5
DATA_DIR = os.environ.get('EB_DATA_DIR', os.getcwd())
TIMEZONE = 'UTC'
MDNS_ENABLED = True
MDNS_NAME = 'EdgeBridge-aeb'
MDNS_TYPE = '_edgebridge._tcp.local.'

registrations = []
hubsenderrors = {}
regdeletelist = []
aeb_sessions = {}
redirects = {}
callbacks = {}

_zeroconf = None
_mdns_info = None
SERVER_ADVERTISED_IP = ''

_st_pat_valid = False
_st_pat_checked_at = 0.0
ST_PAT_TTL = 300

SERVER_STARTED_AT = 0
SERVER_START_STR = ''
BUILD_SHA = os.environ.get('EB_BUILD_SHA', 'dev')[:7]
BUILD_DATE = os.environ.get('EB_BUILD_DATE', '')
DISPLAY_VERSION = VERSION if BUILD_SHA == 'dev' else f'{VERSION}+{BUILD_SHA}'

_fwd_clients = {}

MQTT_RING_MAX = 200

CALLBACK_NAME_REGEX = re.compile(r'^[A-Za-z0-9_\-]+$')
CALLBACK_MAX_VALUE_BYTES = 64 * 1024

DEFAULT_SERVERPORT = 8088
DEFAULT_ST_TOKEN = ''
TOKEN_LENGTH = 36
MAXPORT = 65535
HTTP_OK = 200

CONFIGFILENAME = 'edgebridge.cfg'
REGSFILENAME = '.registrations'
REDIRECTSFILENAME = 'redirects.jsonl'
CALLBACKSFILENAME = 'callbacks.jsonl'
MQTTSESSIONSFILENAME = 'mqtt_sessions.jsonl'
LOGFILE = 'edgebridge.log'

BROWSER_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
