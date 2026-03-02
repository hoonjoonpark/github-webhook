# Webhook listener

github app을 통해서 들어오는 global push event 핸들링.

## 목적

- Ubuntu host에서 `systemd` 로 웹훅 서버를 상시 실행.
- repository 에서 오는 전역 push 이벤트를 받아 배포 스크립트를 실행.
- 주 목적은 Docker 이미지 빌드/푸시 및 서비스 재배포.

## 주요 files

- webhook.py: 웹훅 서버
- deploy-configs/*.yml: repo/branch 별 배포 대상 설정
- deploy-configs/github-webhook.yml.example: webhook 서버 self-update 예시
- deploy-configs/docker-app.yml.example: 일반 Docker 앱 배포 예시
- scripts/deploy-local-registry.sh: host에서 Docker buildx/push/compose 수행
- scripts/install-systemd-service.sh: `systemd` 서비스 설치 보조 스크립트
- systemd/github-webhook.service.example: Ubuntu 서비스 유닛 예시


## Architecture

- webhook 서버는 host에서 `systemd` 로 실행
- 스크립트 실행하는 구성은 yaml 파일로 만들어서, 서버 재시작없이 yaml 파일 추가로 git pull / build / deploy 등을 수행하도록
- push 정보에서 확인할 내용은 repository, branch
- build 성공 후, 로깅 및 send_bot_message(텔레그램 메시징) 처리

## Runtime

- webhook endpoint: `POST /git`
- health check: `GET /healthz`
- GitHub App webhook secret 검증 수행
- `deploy-configs/*.yml` 를 요청 시마다 다시 읽어 repo/branch 매칭
- 매칭된 설정의 `commands` 를 host shell에서 background task 로 실행

## Remote server

- 원격 서버 기준 작업 디렉토리: `/home/hjpark/github-webhook`
- nginx 는 `/git` -> `http://127.0.0.1:9000/git` 으로 proxy pass
- webhook 서버는 `127.0.0.1:9000` 에서 수신
- 로컬이 Apple Silicon 이어도 배포 이미지는 `docker buildx --platform linux/amd64 --push` 로 빌드 가능

## Quick start

1. `cp .env.example .env` 후 값 설정
2. `cp deploy-configs/github-webhook.yml.example deploy-configs/github-webhook.yml`
3. `.env` 의 `WEBHOOK_SECRET`, `TARGET_REPOSITORY`, `TARGET_BRANCH` 설정
4. `pip install -r requirements.txt`
5. `sudo cp systemd/github-webhook.service.example /etc/systemd/system/github-webhook.service`
6. `sudo systemctl daemon-reload && sudo systemctl enable --now github-webhook`

## Example deploy config

```yaml
name: github-webhook-self
repository: my-org/github-webhook
branches:
  - main
workdir: /home/hjpark/github-webhook
commands:
  - git pull --ff-only origin main
  - /home/hjpark/.envs/github-webhook/bin/pip install -r requirements.txt
  - sudo systemctl restart github-webhook
env: {}
```

## Example docker app deploy config

```yaml
name: sample-docker-app
repository: my-org/my-app
branches:
  - main
workdir: /home/hjpark/my-app
commands:
  - /home/hjpark/github-webhook/scripts/deploy-local-registry.sh
env:
  IMAGE_NAME: bth.local:5000/my-app
  IMAGE_TAG: latest
  BUILD_PLATFORM: linux/amd64
  ROOT_DIR: /home/hjpark/my-app
  BUILD_CONTEXT: /home/hjpark/my-app
  DOCKERFILE_PATH: /home/hjpark/my-app/Dockerfile
  COMPOSE_FILE: /home/hjpark/my-app/docker-compose.yml
  SERVICE_NAME: my-app
  RUN_COMPOSE: "1"
```

## Systemd service example

```ini
[Unit]
Description=GitHub Webhook Server
After=network.target

[Service]
Type=simple
User=hjpark
WorkingDirectory=/home/hjpark/github-webhook
EnvironmentFile=/home/hjpark/github-webhook/.env
ExecStart=/usr/bin/env /home/hjpark/.envs/github-webhook/bin/python /home/hjpark/github-webhook/webhook.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

## Logs

- 서비스 로그 확인: `journalctl -u github-webhook -f`
- 최근 200줄 확인: `journalctl -u github-webhook -n 200 --no-pager`

## Notes

- self-deploy 예시는 원격 working tree가 `/home/hjpark/github-webhook` 에 체크아웃되어 있다는 전제
- `deploy-local-registry.sh` 는 host에서 실행된다는 전제이며, 대상 앱이 `docker-compose.yml` 을 사용하지 않으면 `RUN_COMPOSE=0` 으로 꺼둘 수 있음
- `sudo systemctl restart github-webhook` 를 webhook 프로세스가 실행하려면 `hjpark` 에 대한 sudoers 설정이 필요할 수 있음
