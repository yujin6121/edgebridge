import base64
import json
import os
import time
import uuid

import paho.mqtt.client as mqtt
import requests
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from cryptography import x509

from app import state
from app.persistence import data_path, load_jsonl, now_ms, save_jsonl
from app.response import send_json


def _mqtt_cert_dir():
    d = os.path.join(state.DATA_DIR, 'mqtt_certs')
    os.makedirs(d, exist_ok=True)
    return d


def _mqtt_cert_path(session_id, suffix):
    return os.path.join(_mqtt_cert_dir(), f'{session_id}{suffix}')


def _mqtt_session_record(session):
    return {
        'id': session['id'],
        'state': session.get('state', 'CREATED'),
        'seq': session.get('seq', 0),
        'subscribedTopics': session.get('subscribedTopics', []),
        'qos': session.get('qos', 1),
        'forwardTarget': session.get('forwardTarget'),
        'pendingForwardCount': session.get('pendingForwardCount', 0),
        'lastConnectedTs': session.get('lastConnectedTs'),
        'lastForwardOkTs': session.get('lastForwardOkTs'),
        'lastError': session.get('lastError'),
        'ring': session.get('ring', [])[-state.MQTT_RING_MAX:],
        'endpoint': session.get('endpoint'),
        'port': session.get('port', 8883),
        'keepAliveSec': session.get('keepAliveSec', 60),
        'effectiveClientId': session.get('effectiveClientId'),
        'hasCa': bool(session.get('hasCa')),
    }


def save_mqtt_sessions():
    save_jsonl(state.MQTTSESSIONSFILENAME, {
        sid: _mqtt_session_record(session)
        for sid, session in state.aeb_sessions.items()
    })


def load_mqtt_sessions():
    restored = {}
    records = load_jsonl(state.MQTTSESSIONSFILENAME, 'id')
    for rec in records.values():
        session_id = rec.get('id')
        if not session_id:
            continue
        key_path = _mqtt_cert_path(session_id, '.key')
        private_key = None
        if os.path.exists(key_path):
            try:
                with open(key_path, 'rb') as f:
                    private_key = serialization.load_pem_private_key(f.read(), password=None)
            except Exception as e:
                state.log.warn(f'[AEB] Failed to load private key for {session_id}: {e}')

        restored_state = 'RESTORED' if rec.get('endpoint') else rec.get('state', 'CREATED')
        restored[session_id] = {
            'id': session_id,
            'state': restored_state,
            'private_key': private_key,
            'seq': rec.get('seq', 0),
            'client': None,
            'subscribedTopics': rec.get('subscribedTopics', []),
            'qos': rec.get('qos', 1),
            'forwardTarget': rec.get('forwardTarget'),
            'pendingForwardCount': rec.get('pendingForwardCount', 0),
            'lastConnectedTs': rec.get('lastConnectedTs'),
            'lastForwardOkTs': rec.get('lastForwardOkTs'),
            'lastError': rec.get('lastError'),
            'ring': rec.get('ring', [])[-state.MQTT_RING_MAX:],
            'endpoint': rec.get('endpoint'),
            'port': rec.get('port', 8883),
            'keepAliveSec': rec.get('keepAliveSec', 60),
            'effectiveClientId': rec.get('effectiveClientId'),
            'hasCa': bool(rec.get('hasCa')),
        }
    return restored


def _mqtt_prepare_client(session):
    client_id = session.get('effectiveClientId') or f"aeb-{session['id']}"
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
    client.user_data_set(session)
    client.on_message = aeb_on_message
    client.on_connect = aeb_on_connect
    client.on_disconnect = aeb_on_disconnect

    cert_path = _mqtt_cert_path(session['id'], '.crt')
    key_path = _mqtt_cert_path(session['id'], '.key')
    ca_path = _mqtt_cert_path(session['id'], '_ca.crt')
    if session.get('hasCa') and os.path.exists(ca_path):
        client.tls_set(certfile=cert_path, keyfile=key_path, ca_certs=ca_path)
    else:
        client.tls_set(certfile=cert_path, keyfile=key_path)
    return client


def connect_mqtt_session(session, restored=False):
    endpoint = session.get('endpoint')
    if not endpoint:
        session['state'] = 'CREATED'
        return False
    try:
        client = _mqtt_prepare_client(session)
        session['client'] = client
        session['state'] = 'CONNECTING'
        session['lastError'] = None
        if restored:
            client.connect_async(endpoint, session.get('port', 8883), session.get('keepAliveSec', 60))
        else:
            client.connect(endpoint, session.get('port', 8883), session.get('keepAliveSec', 60))
        client.loop_start()
        suffix = ' after restore' if restored else ''
        state.log.info(f"[AEB] {session['id']} connecting{suffix} to {endpoint}:{session.get('port', 8883)}")
        save_mqtt_sessions()
        return True
    except Exception as e:
        session['state'] = 'ERROR'
        session['lastError'] = str(e)
        state.log.error(f"[AEB] Connect failed for {session['id']}: {e}")
        save_mqtt_sessions()
        return False


def restore_mqtt_sessions():
    restored = load_mqtt_sessions()
    state.aeb_sessions.update(restored)
    reconnecting = 0
    for session in restored.values():
        if session.get('endpoint') and os.path.exists(_mqtt_cert_path(session['id'], '.crt')) and os.path.exists(_mqtt_cert_path(session['id'], '.key')):
            if connect_mqtt_session(session, restored=True):
                reconnecting += 1
    if restored:
        state.log.hilite(f' > Restored {len(restored)} MQTT session(s), reconnecting {reconnecting}')


def aeb_get_json_body(server):
    if getattr(server, 'data_bytes', None):
        try:
            return json.loads(server.data_bytes.decode('utf-8'))
        except Exception as e:
            state.log.error(f'[AEB] JSON parse error: {e}')
    return {}


def aeb_on_message(client, userdata, msg, *args, **kwargs):
    session = userdata
    session['seq'] += 1
    try:
        payload_str = msg.payload.decode('utf-8')
        encoding = 'utf8'
    except UnicodeDecodeError:
        payload_str = base64.b64encode(msg.payload).decode('ascii')
        encoding = 'base64'

    forward_data = {
        'sessionId': session['id'],
        'seq': session['seq'],
        'topic': msg.topic,
        'payload': payload_str,
        'payloadEncoding': encoding,
        'ts': now_ms(),
    }

    ring = session['ring']
    ring.append(forward_data)
    if len(ring) > state.MQTT_RING_MAX:
        del ring[0:len(ring) - state.MQTT_RING_MAX]

    target = session.get('forwardTarget')
    if not target:
        session['pendingForwardCount'] = len(ring)
        save_mqtt_sessions()
        return

    delay = 0.5
    for attempt in range(4):
        try:
            r = requests.post(target, json=forward_data, timeout=3)
            if 200 <= r.status_code < 300:
                session['lastForwardOkTs'] = now_ms()
                session['pendingForwardCount'] = 0
                save_mqtt_sessions()
                return
            state.log.warn(f"[AEB] Forward HTTP {r.status_code} (attempt {attempt + 1})")
        except Exception as e:
            session['lastError'] = str(e)
            state.log.warn(f"[AEB] Forward failed (attempt {attempt + 1}): {e}")
        time.sleep(delay)
        delay = min(delay * 2, 4)
    session['lastError'] = 'forward dropped after 4 attempts'
    save_mqtt_sessions()
    state.log.error(f"[AEB] Forward dropped for {session['id']} seq={session['seq']}")


def aeb_on_connect(client, userdata, *args):
    session = userdata
    reason = args[-2] if len(args) >= 2 else 0
    try:
        failed = bool(reason.is_failure)
    except AttributeError:
        failed = (int(reason) != 0)
    if failed:
        session['state'] = 'ERROR'
        session['lastError'] = f'CONNACK failed: {reason}'
        save_mqtt_sessions()
        state.log.error(f"[AEB] {session['id']} CONNACK failed: {reason}")
        return
    session['state'] = 'CONNECTED'
    session['lastConnectedTs'] = now_ms()
    for topic in session.get('subscribedTopics', []):
        client.subscribe(topic, qos=session.get('qos', 1))
    save_mqtt_sessions()
    state.log.info(f"[AEB] {session['id']} CONNECTED; subscribed {session.get('subscribedTopics')}")


def aeb_on_disconnect(client, userdata, *args):
    session = userdata
    if session.get('state') == 'CONNECTED':
        session['state'] = 'DISCONNECTED'
        save_mqtt_sessions()
    state.log.warn(f"[AEB] {session['id']} disconnected")


def handle_aeb_routes(server):
    path = server.path.split('?')[0]
    method = server.command
    parts = path.split('/')

    try:
        if method == 'POST' and path == '/mqtt/sessions':
            req = aeb_get_json_body(server)
            session_id = f"sess_{uuid.uuid4().hex[:12]}"
            private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            subject_cn = req.get('subjectCN', 'AEB Bridge Certificate')
            csr = x509.CertificateSigningRequestBuilder().subject_name(
                x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject_cn)])
            ).sign(private_key, hashes.SHA256())
            csr_pem = csr.public_bytes(serialization.Encoding.PEM).decode('utf-8')

            state.aeb_sessions[session_id] = {
                'id': session_id,
                'state': 'CREATED',
                'private_key': private_key,
                'seq': 0,
                'client': None,
                'subscribedTopics': [],
                'qos': 1,
                'forwardTarget': None,
                'pendingForwardCount': 0,
                'lastConnectedTs': None,
                'lastForwardOkTs': None,
                'lastError': None,
                'ring': [],
                'endpoint': None,
                'port': 8883,
                'keepAliveSec': 60,
                'effectiveClientId': None,
                'hasCa': False,
            }
            key_path = _mqtt_cert_path(session_id, '.key')
            with open(key_path, 'wb') as f:
                f.write(private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.TraditionalOpenSSL,
                    encryption_algorithm=serialization.NoEncryption()))
            save_mqtt_sessions()
            state.log.info(f'[AEB] Created session {session_id}')
            send_json(server, 201, {'sessionId': session_id, 'csrPem': csr_pem, 'state': 'CREATED'})
            return True

        if method == 'POST' and len(parts) == 5 and parts[4] == 'connect':
            session_id = parts[3]
            session = state.aeb_sessions.get(session_id)
            if not session:
                send_json(server, 404, {'error': {'code': 'SESSION_NOT_FOUND', 'message': 'Not found'}})
                return True

            req = aeb_get_json_body(server)
            topics = req.get('topics', [])
            if not topics:
                send_json(server, 400, {'error': {'code': 'NO_TOPICS', 'message': 'topics requires >= 1 entry'}})
                return True
            qos = req.get('qos', 1)
            if qos not in (0, 1):
                send_json(server, 400, {'error': {'code': 'BAD_QOS', 'message': 'qos must be 0 or 1'}})
                return True

            cdir = _mqtt_cert_dir()
            cert_path = os.path.join(cdir, f'{session_id}.crt')
            key_path = os.path.join(cdir, f'{session_id}.key')
            with open(cert_path, 'w') as f:
                f.write(req['certPem'])
            if session.get('private_key'):
                with open(key_path, 'wb') as f:
                    f.write(session['private_key'].private_bytes(
                        encoding=serialization.Encoding.PEM,
                        format=serialization.PrivateFormat.TraditionalOpenSSL,
                        encryption_algorithm=serialization.NoEncryption()))

            if req.get('caPem'):
                ca_path = os.path.join(cdir, f'{session_id}_ca.crt')
                with open(ca_path, 'w') as f:
                    f.write(req['caPem'])

            session['subscribedTopics'] = topics
            session['qos'] = qos
            session['effectiveClientId'] = req.get('clientId') or f'aeb-{session_id}'
            session['endpoint'] = req['endpoint']
            session['port'] = req.get('port', 8883)
            session['keepAliveSec'] = req.get('keepAliveSec', 60)
            session['hasCa'] = bool(req.get('caPem'))

            if connect_mqtt_session(session):
                send_json(server, 200, {
                    'sessionId': session_id,
                    'state': 'CONNECTING',
                    'subscribedTopics': topics,
                })
            else:
                send_json(server, 500, {'error': {'code': 'CONNECT_FAILED', 'message': session.get('lastError')}})
            return True

        if method == 'PUT' and len(parts) == 5 and parts[4] == 'forward':
            session_id = parts[3]
            session = state.aeb_sessions.get(session_id)
            if not session:
                send_json(server, 404, {'error': {'code': 'SESSION_NOT_FOUND', 'message': 'Not found'}})
                return True
            req = aeb_get_json_body(server)
            hub_ip = req.get('hubAddress') or server.client_address[0]
            hub_port = req['hubPort']
            fwd_path = req.get('path') or '/aeb/ingest'
            forward_target = f'http://{hub_ip}:{hub_port}{fwd_path}'
            session['forwardTarget'] = forward_target
            state.log.info(f'[AEB] {session_id} forward target: {forward_target}')
            if session['ring']:
                buffered = list(session['ring'])
                session['ring'].clear()
                for item in buffered:
                    try:
                        requests.post(forward_target, json=item, timeout=3)
                        session['lastForwardOkTs'] = now_ms()
                    except Exception as e:
                        session['lastError'] = str(e)
                session['pendingForwardCount'] = 0
            save_mqtt_sessions()
            send_json(server, 200, {'sessionId': session_id, 'forwardTarget': forward_target})
            return True

        if method == 'GET' and len(parts) == 5 and parts[4] == 'status':
            session_id = parts[3]
            session = state.aeb_sessions.get(session_id)
            if not session:
                send_json(server, 404, {'error': {'code': 'SESSION_NOT_FOUND', 'message': 'Not found'}})
                return True
            status = {
                'sessionId': session_id,
                'state': session.get('state', 'CREATED'),
                'subscribedTopics': session.get('subscribedTopics', []),
                'forwardTarget': session.get('forwardTarget'),
                'pendingForwardCount': session.get('pendingForwardCount', 0),
                'lastConnectedTs': session.get('lastConnectedTs'),
                'lastForwardOkTs': session.get('lastForwardOkTs'),
                'lastError': session.get('lastError'),
            }
            if session.get('effectiveClientId'):
                status['effectiveClientId'] = session['effectiveClientId']
                status['liveClientIdConnections'] = 1 if session.get('state') == 'CONNECTED' else 0
            send_json(server, 200, status)
            return True

        if method == 'GET' and len(parts) == 5 and parts[4] == 'messages':
            session_id = parts[3]
            session = state.aeb_sessions.get(session_id)
            if not session:
                send_json(server, 404, {'error': {'code': 'SESSION_NOT_FOUND', 'message': 'Not found'}})
                return True
            since = 0
            q = server.path.split('?', 1)
            if len(q) == 2 and q[1].startswith('since='):
                try:
                    since = int(q[1][6:])
                except ValueError:
                    since = 0
            msgs = [m for m in session['ring'] if m['seq'] > since]
            cursor = str(msgs[-1]['seq']) if msgs else str(since)
            send_json(server, 200, {'messages': msgs, 'cursor': cursor})
            return True

        if method == 'DELETE' and len(parts) == 4:
            session_id = parts[3]
            session = state.aeb_sessions.pop(session_id, None)
            if session and session.get('client'):
                try:
                    session['client'].loop_stop()
                    session['client'].disconnect()
                except Exception:
                    pass
            for suffix in ('.crt', '.key', '_ca.crt'):
                p = os.path.join(_mqtt_cert_dir(), f'{session_id}{suffix}')
                try:
                    os.remove(p)
                except OSError:
                    pass
            save_mqtt_sessions()
            send_json(server, 200, {'sessionId': session_id, 'deleted': True})
            return True

    except Exception as e:
        state.log.error(f'[AEB] Error: {e}')
        send_json(server, 500, {'error': {'code': 'INTERNAL_ERROR', 'message': str(e)}})
        return True

    return False
