#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${ROOT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
IMAGE_NAME="${IMAGE_NAME:-bth.local:5000/github-webhook}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
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
