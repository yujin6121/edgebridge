# edgebridge-aeb

> [WooBooung/edgebridge](https://github.com/WooBooung/edgebridge) 기반의 SmartThings Edge 브리지입니다.

## 빠른 시작 (Docker)

기본 권장 방식은 Docker host 네트워크입니다. mDNS 자동 발견, 허브 포워딩, MQTT 포워딩은 실제 LAN IP가 중요하기 때문에 bridge 네트워크보다 host 네트워크가 안정적입니다.

### Docker run

Docker Hub 이미지를 사용하는 경우:

```sh
mkdir -p ./data

docker run -d --name edgebridge-aeb \
  --network host \
  -v $(pwd)/data:/data \
  --restart unless-stopped \
  woobooung/edgebridge-aeb:latest
```

소스에서 직접 빌드하는 경우:

```sh
docker build -t edgebridge-aeb .

docker run -d --name edgebridge-aeb \
  --network host \
  -v $(pwd)/data:/data \
  --restart unless-stopped \
  edgebridge-aeb
```

접속:

```text
http://<host-ip>:8088
http://<host-ip>:8088/web
```

PAT를 함께 넣어 실행하려면:

```sh
docker run -d --name edgebridge-aeb \
  --network host \
  -v $(pwd)/data:/data \
  -e EB_ST_TOKEN=<36자 SmartThings PAT> \
  --restart unless-stopped \
  woobooung/edgebridge-aeb:latest
```

호스트의 8088 포트가 이미 사용 중이면 `EB_SERVER_PORT`로 변경할 수 있습니다.

### Docker Compose

저장소의 `docker-compose.yml`은 host 네트워크 + 소스 빌드(`build: .`)를 사용합니다.

```sh
docker compose up -d
```

기본 설정:

- **네트워크**: host — 포트 매핑이 없으며 호스트의 `Server_Port`(기본 8088)에 직접 바인딩됩니다.
- **데이터**: `./data` 볼륨 → 컨테이너 `/data`
- **재시작**: `unless-stopped`

환경 변수는 compose 파일에 주석 처리된 예시를 참고해 추가할 수 있습니다:

```yaml
environment:
  - EB_ST_TOKEN=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx   # optional SmartThings PAT
  - EB_SERVER_PORT=8088                                # change if 8088 is taken
```

선택적으로 설정 파일을 마운트할 수도 있습니다:

```yaml
volumes:
  - ./edgebridge.cfg:/usr/src/app/edgebridge.cfg
```

> `docker-compose.bridge.yml`은 이 저장소에 포함되어 있지 않습니다. 포트 격리(bridge 네트워크)가 필요하면 직접 작성해야 합니다. 단, bridge 네트워크에서는 mDNS 자동 발견과 실제 클라이언트 IP 기반 기능(디바이스→허브 포워딩, MQTT 허브 포워딩)이 제한될 수 있으며, 단순 `/api/forward`만 사용하는 경우에는 문제없습니다.

## 데이터 저장

컨테이너의 `/data`에 아래 파일과 폴더가 영속 저장됩니다.

```text
.registrations
redirects.jsonl
callbacks.jsonl
mqtt_sessions.jsonl
mqtt_certs/
install_id
```

MQTT 세션은 `mqtt_sessions.jsonl`에 메타데이터가 저장됩니다. 브리지 재시작 시 기존 세션을 복구하고, 인증서/키와 endpoint 정보가 남아 있는 세션은 자동 재연결을 시도합니다.

## 설정

Docker에서는 환경 변수 사용을 권장합니다.

| 환경 변수 | 설명 | 기본값 |
| --- | --- | --- |
| `EB_ST_TOKEN` | SmartThings PAT. `api.smartthings.com` 요청에 자동 주입 | 없음 |
| `EB_SERVER_PORT` | 서버 포트 | `8088` |
| `EB_SERVER_IP` | 바인딩 IP. 보통 비워둠 | 자동 |
| `EB_FW_TIMEOUT` | forward 타임아웃, 초 | `5` |
| `EB_MDNS_ENABLED` | mDNS 끄기: `no`, `false`, `0` | 켜짐 |
| `EB_MDNS_NAME` | mDNS 광고 이름 | `EdgeBridge-aeb` |
| `EB_DATA_DIR` | 데이터 저장 경로 | `/data` |
| `EB_TZ` | 로그 타임존 | `UTC` |

파일로 관리하고 싶으면 `edgebridge.cfg`를 컨테이너의 `/usr/src/app/edgebridge.cfg`에 마운트합니다.

```ini
[config]
Server_IP =
Server_Port = 8088
SmartThings_Bearer_Token =
forwarding_timeout = 5
console_output = yes
logfile_output = no
logfile = edgebridge.log
Data_Dir =
mDNS_enabled = yes
mDNS_name = EdgeBridge-aeb
Timezone = UTC
```

Docker 환경에서는 `Data_Dir`를 비워두는 것이 좋습니다. 이미지가 기본적으로 `EB_DATA_DIR=/data`를 사용합니다.

REST API 문서는 [API.md](API.md)를 참고하세요.

참고 Edge 드라이버: [WooBooung/EdgeBridgeBaseDriver](https://github.com/WooBooung/EdgeBridgeBaseDriver)

## 웹 대시보드

```text
http://<host-ip>:8088/web
```

대시보드에서 확인할 수 있는 항목:

- 브리지 버전, 포트, 데이터 경로
- SmartThings PAT 설정/검증 상태
- mDNS 상태
- MQTT 세션 목록
- redirect/callback 목록
- 등록된 device to hub forwarding 목록
- 최근 로그

일부 설정은 대시보드에서 수정할 수 있습니다.

## 네트워크 모드

권장: host 네트워크

```sh
docker run -d --name edgebridge-aeb \
  --network host \
  -v $(pwd)/data:/data \
  --restart unless-stopped \
  woobooung/edgebridge-aeb:latest
```

host 네트워크가 필요한 기능:

- mDNS 자동 발견
- device to hub forwarding
- MQTT 메시지 허브 포워딩
- 클라이언트 실제 LAN IP 감지

bridge 네트워크를 쓰면 컨테이너에서 요청 출발지가 Docker gateway IP로 보일 수 있습니다. 단순 `/api/forward`만 쓰는 경우에는 bridge 네트워크도 사용할 수 있습니다.

## 직접 실행

Docker 없이 실행할 수도 있습니다.

```sh
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 edgebridge.py
```

디버그 로그는 `-d` 플래그로 켭니다:

```sh
python3 edgebridge.py -d
```

직접 실행 시 데이터는 **실행 디렉터리**(`Data_Dir` 또는 `EB_DATA_DIR`로 변경 가능)에 저장됩니다. mDNS는 실제 호스트 네트워크 인터페이스에서 동작합니다.

운영 환경에서는 Docker 실행을 권장합니다.

## 감사

- MQTT 브리지 참고 구현을 공유해주신 두더싱 스마트싱스 네이버 카페 산사나이님께 감사드립니다.
- edgebridge 프로젝트를 공개해주신 Todd Austin 및 contributors께 감사드립니다.

관련 링크:

- [WooBooung/edgebridge](https://github.com/WooBooung/edgebridge)
- [AndroidEdgeBridge(AEB)](https://aeb.dothesmartthings.com)
- [AEB 개발자 가이드](https://aeb.dothesmartthings.com/dev-guide.html)
- [두더싱 스마트싱스 네이버 카페](https://cafe.naver.com/dothesmartthings)

## 라이선스

Apache License 2.0
