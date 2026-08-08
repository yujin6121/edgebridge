# 🚀 edgebridge

> 🇰🇷 SmartThings Edge 브리지 (EdgeBridge 기반)  
> 🇺🇸 SmartThings Edge Bridge based on EdgeBridge

![Docker](https://img.shields.io/badge/docker-ready-blue)
![Status](https://img.shields.io/badge/status-active-success)
![License](https://img.shields.io/badge/license-Apache%202.0-green)

---

## ✨ 특징 | Features

### 🇰🇷
- ✅ SmartThings Edge 브리지
- 🌐 mDNS 자동 발견 지원
- 🔄 MQTT 포워딩 지원
- 🐳 Docker 기반 실행
- ⚡ 빠른 설치 및 간편한 설정

### 🇺🇸
- ✅ SmartThings Edge bridge
- 🌐 Supports mDNS auto discovery
- 🔄 MQTT forwarding support
- 🐳 Docker-based deployment
- ⚡ Fast setup and easy configuration

---

## 📑 목차 | Table of Contents

- [빠른 시작 / Quick Start](#-빠른-시작--quick-start)
- [설정 / Configuration](#-설정--configuration)
- [데이터 저장 / Data Storage](#-데이터-저장--data-storage)
- [웹 대시보드 / Web Dashboard](#-웹-대시보드--web-dashboard)

---

## ⚡ 빠른 시작 | Quick Start

### 🐳 Docker (권장 / Recommended)

### 🇰🇷
Docker host 네트워크 사용을 권장합니다.  
mDNS 및 실제 LAN IP 기반 기능에서 더 안정적입니다.

### 🇺🇸
Using Docker with host network is recommended.  
It ensures stable mDNS discovery and LAN-based features.

---

### ▶ Docker Run (빌드 포함 | build & run)

```bash
# 1) 저장소 클론 | Clone the repository
git clone https://github.com/yujin6121/edgebridge.git
cd edgebridge

# 2) 이미지 빌드 | Build the image (local)
docker build -t edgebridge:latest .

# 3) 실행 | Run (host 네트워크 권장 / host network recommended)
mkdir -p ./data
docker run -d --name edgebridge \
  --network host \
  -v $(pwd)/data:/data \
  --restart unless-stopped \
  edgebridge:latest
```

---

### 🌐 접속 | Access

```
http://<host-ip>:8088
http://<host-ip>:8088/web
```

---

### 🔑 PAT 포함 실행 | Run with PAT

```bash
docker run -d --name edgebridge \
  --network host \
  -v $(pwd)/data:/data \
  -e EB_ST_TOKEN=<SmartThings PAT> \
  --restart unless-stopped \
  edgebridge:latest
```

---

### ▶ Docker Compose

```bash
git clone https://github.com/yujin6121/edgebridge.git
cd edgebridge
docker compose up -d
```

저장소의 `docker-compose.yml`은 host 네트워크 + 소스 빌드(`build: .`)를 사용하며 로컬에 이미지를 빌드합니다. 데이터는 `./data` 볼륨에 저장되고 재시작은 `unless-stopped`입니다.

---

### ⚠️ 포트 변경 | Change Port

### 🇰🇷
8088 포트가 사용 중이면 `EB_SERVER_PORT` 환경 변수를 사용하세요.

### 🇺🇸
If port 8088 is in use, change it using `EB_SERVER_PORT`.

---

## ⚙️ 설정 | Configuration

### 환경 변수 | Environment Variables

| 변수 | 설명 (KR) | Description (EN) | 기본값 |
|------|----------|----------------|--------|
| `EB_ST_TOKEN` | SmartThings PAT | SmartThings token | 없음 |
| `EB_SERVER_PORT` | 서버 포트 | Server port | 8088 |
| `EB_SERVER_IP` | 바인딩 IP | Bind IP | 자동 |
| `EB_FW_TIMEOUT` | 타임아웃 | Forward timeout | 5 |
| `EB_MDNS_ENABLED` | mDNS 비활성화 | Disable mDNS | 활성 |
| `EB_MDNS_NAME` | mDNS 이름 | mDNS name | EdgeBridge-aeb |
| `EB_DATA_DIR` | 데이터 경로 | Data directory | /data |
| `EB_TZ` | 타임존 | Timezone | UTC |

---

### 📄 설정 파일 | Config File

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

---

## 💾 데이터 저장 | Data Storage

### 🇰🇷
컨테이너 `/data` 경로에 아래 데이터가 저장됩니다.

### 🇺🇸
The following data is persisted in `/data`:

```
.registrations
redirects.jsonl
callbacks.jsonl
mqtt_sessions.jsonl
mqtt_certs/
install_id
```

### 🇰🇷
MQTT 세션은 자동 복구 및 재연결을 지원합니다.

### 🇺🇸
MQTT sessions are automatically restored and reconnected.

---

## 🌐 웹 대시보드 | Web Dashboard

```
http://<host-ip>:8088/web
```

### 🇰🇷
브라우저에서 접속하여 상태 및 설정을 확인할 수 있습니다.

### 🇺🇸
Access via browser to monitor and manage the service.

---

## 🧠 네트워크 모드 | Network Mode

### 🇰🇷
- host 네트워크 권장
- bridge 사용 시 일부 기능 제한

### 🇺🇸
- host network recommended
- bridge mode may limit some features

---

## 🔗 참고 | References

- EdgeBridge 기반 프로젝트  
  https://github.com/WooBooung/edgebridge

- Edge 드라이버  
  https://github.com/WooBooung/EdgeBridgeBaseDriver

---

## 📄 라이선스 | License

Apache 2.0 License

---

## 🙌 기여 | Contributing

PR 및 이슈 환영합니다!

Contributions and issues are welcome!
