#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${ROOT_DIR:-/workspace}"
COMPOSE_FILE="${COMPOSE_FILE:-${ROOT_DIR}/docker-compose.yml}"
IMAGE_NAME="${IMAGE_NAME:-bth.local:5000/github-webhook}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
SERVICE_NAME="${SERVICE_NAME:-github-webhook}"
BUILD_CONTEXT="${BUILD_CONTEXT:-${ROOT_DIR}}"
DOCKERFILE_PATH="${DOCKERFILE_PATH:-${ROOT_DIR}/Dockerfile}"
BUILD_PLATFORM="${BUILD_PLATFORM:-linux/amd64}"

echo "Building and pushing ${IMAGE_NAME}:${IMAGE_TAG} for ${BUILD_PLATFORM}"

docker buildx build \
  --platform "${BUILD_PLATFORM}" \
  -t "${IMAGE_NAME}:${IMAGE_TAG}" \
  -f "${DOCKERFILE_PATH}" \
  --push \
  "${BUILD_CONTEXT}"

docker pull "${IMAGE_NAME}:${IMAGE_TAG}"
docker compose -f "${COMPOSE_FILE}" --project-directory "${ROOT_DIR}" up -d --force-recreate --remove-orphans "${SERVICE_NAME}"
