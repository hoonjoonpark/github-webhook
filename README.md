# Webhook listener

github app을 통해서 들어오는 global push event 핸들링.

## 목적

- Docker로 웹훅 서버를 띄워두고, repository 에서 오는 전역 push이벤트를 받아서 작업을 수행.
- 주 목적은 도커 이미지 빌드 및 재배포.

## 주요 files

- webhook.py: 웹훅 서버
- deploy-configs/*.yml: repo/branch 별 배포 대상 설정
- scripts/deploy-local-registry.sh: 로컬 registry 빌드/푸시/재기동 스크립트
- docker-compose.yml: 원격 서버 실행용 compose


## Architecture

- docker compose 로 구성
- 스크립트 실행하는 구성은 yaml 파일로 만들어서, 서버 재시작없이 yaml파일 추가로 git pull / build / deploy등을 수행하도록.
- push 정보에서 확인할 내용은 repository, branch
- build 성공 후, 로깅 및 send_bot_message(텔레그램 메시징) 처리

## Runtime

- webhook endpoint: `POST /git`
- health check: `GET /healthz`
- GitHub App webhook secret 검증 수행
- `deploy-configs/*.yml` 를 요청 시마다 다시 읽어 repo/branch 매칭
- 매칭된 설정의 `commands` 를 background task 로 실행

## Remote server

- 원격 서버 기준 작업 디렉토리: `/home/hjpark/github-webhook`
- nginx 는 `/git` -> `http://127.0.0.1:9000/git` 으로 proxy pass
- compose 는 host `9000:9000` 으로 바인딩
- Docker image registry: `bth.local:5000/github-webhook`
- 로컬이 Apple Silicon 이어도 배포 이미지는 `docker buildx --platform linux/amd64 --push` 로 빌드

## Quick start

1. `cp .env.example .env` 후 값 설정
2. `cp deploy-configs/github-webhook.yml.example deploy-configs/github-webhook.yml`
3. `.env` 의 `TARGET_REPOSITORY`, `TARGET_BRANCH` 설정
4. `pip install -r requirements.txt`
5. `uvicorn webhook:app --host 0.0.0.0 --port 9000`

## Example deploy config

```yaml
name: github-webhook-self
repository: my-org/github-webhook
branches:
  - main
workdir: /workspace
commands:
  - ./scripts/deploy-local-registry.sh
env:
  IMAGE_NAME: bth.local:5000/github-webhook
  IMAGE_TAG: latest
  BUILD_PLATFORM: linux/amd64
  BUILD_CONTEXT: /workspace
  DOCKERFILE_PATH: /workspace/Dockerfile
```
