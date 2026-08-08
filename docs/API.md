# edgebridge-aeb REST API

기준 주소: `http://<bridge-ip>:8088` (포트는 `EB_SERVER_PORT`로 변경 가능)

## 공통 규칙

- 모든 요청/응답 본문은 `Content-Length`가 **UTF-8 바이트 기준**으로 계산됩니다. 한글/CJK 멀티바이트 응답이 잘리지 않습니다.
- 관리/제어 API(`/api/*`, `/mqtt/*`)에는 **인증이 없습니다**. LAN 내에서 누구나 접근할 수 있으므로 외부 노출 시 주의하세요.
- 에러는 대부분 HTTP 상태 코드로만 판별되며, 일부 엔드포인트는 `{ "error": { "code": ..., "message": ... } }` 형태로 반환합니다.

## 엔드포인트 요약

| Method | Path | 설명 |
|--------|------|------|
| `GET/POST` | `/api/ping` | 브리지 상태 · 헬스 체크 |
| `GET` | `/api/dashboard` | 웹 대시보드 요약 (registrations/redirects/callbacks/mqtt) |
| `GET/POST/PUT/DELETE/PATCH` | `/api/forward?url=` | 외부 API 포워딩 프록시 |
| `POST/DELETE` | `/api/register` | 디바이스 → 허브 forwarding 등록 |
| `POST/DELETE/GET` | `/api/redirect` | 경로 → URL 302 리다이렉트 매핑 |
| `POST/DELETE/GET` | `/api/callback` | name 키 값 저장/조회 |
| `GET` | `/api/logs` | 최근 로그 버퍼 |
| `GET/POST/PUT` | `/api/settings` | 브리지 설정 조회/변경 |
| `GET` | `/api/llm` | 지원 안 함 (항상 404) |
| — | `/mqtt/*` | mTLS MQTT 세션 관리 (하단 참조) |

---

## `/api/ping`

브리지 상태 및 헬스 체크를 반환합니다. GET/POST 모두 동작합니다.

```text
GET  /api/ping
POST /api/ping
```

### 응답 예시

```json
{
  "battery": 100,
  "bridgeDevice": "server",
  "bridgeVersion": "1.0.1_AEB+abc1234",
  "build": "abc1234",
  "buildDate": "",
  "serverStartTime": "07/27 14:30",
  "supportedAiOptions": [],
  "stOauthConnected": true,
  "stTokenConfigured": true,
  "stTokenValid": true,
  "accessTokenExpiresAt": null,
  "accessTokenMinutesLeft": null,
  "mqtt": {
    "total": 1,
    "connected": 1,
    "sessions": [
      { "id": "sess_ab12cd34ef56", "state": "CONNECTED", "lastError": null }
    ]
  },
  "blocked": { "hosts": 0, "attempts": 0 }
}
```

### 필드

| 필드 | 설명 |
|------|------|
| `bridgeVersion` | 버전 문자열 (빌드 SHA 포함) |
| `build` / `buildDate` | 빌드 식별자 (CI에서 주입) |
| `stTokenConfigured` | PAT가 설정되어 있는지 여부 |
| `stTokenValid` | PAT가 SmartThings API에서 유효한지 (5분 캐시) |
| `stOauthConnected` | `stTokenValid`와 동일 |
| `mqtt.total` / `mqtt.connected` | 전체/연결된 MQTT 세션 수 |
| `mqtt.sessions` | 세션별 상태 배열 (`id`, `state`, `lastError`) |
| `blocked` | 예약 필드 (항상 0) |

---

## `/api/dashboard`

웹 대시보드(`/web`)가 사용하는 요약 정보를 반환합니다.

```text
GET /api/dashboard
```

> 이전 문서의 `/api/web`는 실제 코드에서는 `/api/dashboard`입니다.

### 응답 예시

```json
{
  "bridge": { /* /api/ping 응답과 동일 */ },
  "registrations": [
    { "devaddr": "192.168.0.10:12345", "edgeid": "driver-id", "hubaddr": "192.168.0.20:12345" }
  ],
  "redirects": [
    { "path": "/tesla", "targetBase": "https://owner-api.teslamotors.com/api", "createdAt": 1717689000000 }
  ],
  "callbacks": [
    { "name": "mytoken", "value": "xxx", "createdAt": 1717689000000 }
  ],
  "mqttSessions": [
    {
      "id": "sess_ab12cd34ef56",
      "state": "CONNECTED",
      "subscribedTopics": ["device/+/state"],
      "forwardTarget": "http://192.168.0.20:12345/aeb/ingest",
      "pendingForwardCount": 0,
      "lastConnectedTs": 1717689874000,
      "lastForwardOkTs": 1717689900000,
      "lastError": null,
      "effectiveClientId": "my-device-id"
    }
  ],
  "server": {
    "version": "1.0.1_AEB",
    "dataDir": "/data",
    "serverPort": 8088,
    "serverIp": "192.168.0.100",
    "mdnsEnabled": true,
    "mdnsName": "EdgeBridge-aeb"
  },
  "generatedAt": 1717689900000
}
```

> `callbacks[].value`에 저장된 원문 값이 평문으로 포함됩니다. 민감한 값은 callback에 저장하지 마세요.

---

## `/api/forward`

SmartThings Edge 드라이버가 외부 HTTP API를 호출할 수 있도록 포워딩합니다.

```text
GET|POST|PUT|DELETE|PATCH /api/forward?url=<URL>
```

### 동작

- `url` 파라미터는 쿼리의 **첫 번째** 파라미터여야 합니다.
- 요청 본문(`Content-Length`로 읽은 원시 바이트)이 그대로 업스트림으로 전달됩니다.
- `api.smartthings.com` 대상이고 요청에 `Authorization`이 없으면 설정된 PAT가 자동 주입됩니다.
- `httpx`가 설치된 경우 **HTTP/2 + TLS 1.3**을 사용합니다. Tesla owner-api 등은 TLS 1.3이 강제됩니다.
- 응답은 업스트림의 **원시 바이트**와 `Content-Type`을 그대로 반환합니다.

### 상태 코드

| 코드 | 의미 |
|------|------|
| `200` | 성공 |
| `400` | URL 누락 |
| `405` | 지원하지 않는 HTTP 메서드 |
| `502` | 업스트림 요청 실패 (Bad Gateway) |

---

## `/api/register`

SmartThings Edge 디바이스의 hub forwarding 등록을 관리합니다. 등록된 디바이스 IP에서 들어오는 요청은 등록된 허브로 전달됩니다.

```text
POST   /api/register?devaddr=<ip>:<port>&hubaddr=<ip>:<port>&edgeid=<id>
DELETE /api/register?devaddr=<ip>:<port>&hubaddr=<ip>:<port>&edgeid=<id>
```

- `devaddr`, `hubaddr`은 `ip` 또는 `ip:port` 형식, `edgeid`는 8-4-4-4-12 형식의 UUID입니다.
- POST: 디바이스 등록 (동일 `devaddr`+`edgeid`가 있으면 교체)
- DELETE: 등록 해제. 현재 코드는 POST와 동일하게 **세 파라미터 모두를 요구**합니다 (`hubaddr` 없으면 400).

### 상태 코드

| 코드 | 의미 |
|------|------|
| `200` | 성공 |
| `400` | 인자 누락 또는 형식 오류 |
| `404` | 삭제할 등록이 없음 |
| `405` | 지원하지 않는 HTTP 메서드 |

---

## `/api/redirect`

브리지 경로를 외부 URL로 302 리다이렉트하는 매핑을 관리합니다.

```text
POST   /api/redirect?path=<path>&target=<url>
DELETE /api/redirect?path=<path>
GET    /api/redirect
```

- POST: 경로 매핑 등록. `target`은 `http://` 또는 `https://`로 시작해야 합니다.
  - `path`는 정규화됩니다: 앞뒤 공백 제거, `/` 없는 경우 추가, 마지막 `/` 제거, **소문자 변환**.
- DELETE: 경로 매핑 제거
- GET: 전체 리다이렉트 목록 반환 (JSON 배열)

등록 후 `<path>/...`로 들어온 요청은 `target + 나머지 경로 + 쿼리`로 302 리다이렉트됩니다. 가장 긴 일치 경로가 우선합니다.

### 상태 코드

| 코드 | 의미 |
|------|------|
| `200` | 성공 |
| `400` | 파라미터 누락 또는 `target` 형식 오류 |
| `405` | 지원하지 않는 HTTP 메서드 |

---

## `/api/callback`

name 키로 임의의 값을 저장하고 조회합니다.

```text
POST   /api/callback?name=<name>
DELETE /api/callback?name=<name>
GET    /api/callback
GET    /api/callback/<name>
```

- POST: 값 저장. 본문은 **plain text**이며 최대 64KB.
- DELETE: 값 삭제
- GET `/api/callback`: 전체 목록 반환 (JSON 배열)
- GET `/api/callback/<name>`: 특정 name의 값 반환 (plain text)
- `name`은 `[A-Za-z0-9_-]+`만 허용합니다.

### 상태 코드

| 코드 | 의미 |
|------|------|
| `200` | 성공 |
| `400` | name 누락/형식 오류, 또는 값이 64KB 초과 |
| `404` | name을 찾을 수 없음 |
| `405` | 지원하지 않는 HTTP 메서드 |

---

## `/api/logs`

최근 로그 버퍼(최대 1000건)를 반환합니다. 각 항목은 **객체**입니다.

```text
GET /api/logs
```

### 응답 예시

```json
{
  "logs": [
    { "ts": 1717689900000, "level": "info", "msg": "Sending GET to https://api.smartthings.com/..." },
    { "ts": 1717689901000, "level": "warn", "msg": "[AEB] sess_ab12cd34ef56 disconnected" }
  ]
}
```

- `ts`: epoch milliseconds
- `level`: `info` | `warn` | `error` | `hilite` | `debug`

---

## `/api/settings`

브리지 설정을 조회하거나 변경합니다. 인증이 없으므로 **PAT 원문은 반환되지 않습니다**.

```text
GET  /api/settings
POST /api/settings
PUT  /api/settings
```

### GET 응답 예시

```json
{
  "forwardingTimeout": 5,
  "mdnsEnabled": true,
  "mdnsName": "EdgeBridge-aeb",
  "stTokenConfigured": true,
  "serverIp": "",
  "serverPort": 8088,
  "timezone": "UTC",
  "dataDir": "/data",
  "source": {
    "configFile": "/usr/src/app/edgebridge.cfg",
    "envOverrides": {
      "EB_ST_TOKEN": true,
      "EB_FW_TIMEOUT": false,
      "EB_MDNS_ENABLED": false,
      "EB_MDNS_NAME": false,
      "EB_TZ": false
    }
  }
}
```

### POST/PUT 요청 본문 예시

```json
{
  "forwardingTimeout": 10,
  "mdnsEnabled": true,
  "mdnsName": "MyBridge",
  "stToken": "36자리_SmartThings_PAT"
}
```

### 변경 가능한 항목

| 필드 | 설명 |
|------|------|
| `forwardingTimeout` | 포워딩 타임아웃 (초, 1 이상 정수) |
| `mdnsEnabled` | mDNS 활성화 여부 |
| `mdnsName` | mDNS 광고 이름 (비어 있으면 400) |
| `stToken` | SmartThings PAT (36자. 빈 값은 무시 → 초기화 불가) |

변경 사항은 `edgebridge.cfg`에 기록되고, mDNS 설정이 바뀌면 즉시 재시작됩니다.

### POST/PUT 응답 예시

```json
{
  "ok": true,
  "settings": { /* GET과 동일 */ },
  "changed": { "forwardingTimeout": 10, "mdnsEnabled": true }
}
```

### 에러

| 상태 | code | 의미 |
|------|------|------|
| `400` | `BAD_SETTINGS` | 값 형식 오류 (예: 36자가 아닌 PAT) |
| `500` | `SETTINGS_UPDATE_FAILED` | 설정 파일 쓰기 실패 |
| `405` | `METHOD_NOT_ALLOWED` | 지원하지 않는 메서드 |

---

## `/api/llm`

원본 프로젝트의 LLM 엔드포인트는 edgebridge-aeb에서 의도적으로 미포팅되어 있습니다. 항상 404를 반환합니다.

```text
GET /api/llm
```

```json
{ "error": { "code": "NOT_SUPPORTED", "message": "LLM endpoint not available in edgebridge-aeb" } }
```

---

## `/mqtt/*`

외부 MQTT 브로커에 mTLS로 연결해 토픽을 구독하고, 수신 메시지를 허브 Edge 드라이버로 HTTP 전달합니다.

| Method | Path | 설명 |
|--------|------|------|
| `POST` | `/mqtt/sessions` | 세션 생성, RSA2048 키쌍 생성, CSR 반환 |
| `POST` | `/mqtt/sessions/{id}/connect` | 인증서로 MQTT 브로커 연결 및 토픽 구독 |
| `PUT` | `/mqtt/sessions/{id}/forward` | 허브 포워딩 대상 등록 |
| `GET` | `/mqtt/sessions/{id}/status` | 세션 상태 조회 |
| `GET` | `/mqtt/sessions/{id}/messages?since=` | 링버퍼 메시지 조회 |
| `DELETE` | `/mqtt/sessions/{id}` | 세션 종료 및 인증서/키 삭제 |

> 스펙(v0.3)상 `X-AEB-Api-Version: 1` 헤더가 필요하다고 명시되어 있으나, 현재 브리지 코드는 이 헤더를 **검증하지 않습니다**.

자세한 계약 및 메시지 포맷, 상태 머신은 [mqtt-bridge-spec-v0.3.md](mqtt-bridge-spec-v0.3.md)를 참고하세요.

---

## 보안 주의사항

- `/api/settings`, `/api/callback`, `/api/register`, `/api/redirect`, `/mqtt/*`는 **인증 없이** 동작합니다. LAN 외부(인터넷) 노출 시 반드시 방화벽/리버스 프록시 인증을 두세요.
- `/api/dashboard`는 callback 원문 값을 포함합니다.
- `/api/forward`는 임의 URL로 프록시가 가능합니다 (SSRF 성격). 신뢰할 수 있는 드라이버만 사용하세요.
