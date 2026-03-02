#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${SERVICE_NAME:-github-webhook}"
SERVICE_SOURCE="${SERVICE_SOURCE:-/home/hjpark/github-webhook/systemd/${SERVICE_NAME}.service.example}"
SERVICE_TARGET="${SERVICE_TARGET:-/etc/systemd/system/${SERVICE_NAME}.service}"

sudo cp "${SERVICE_SOURCE}" "${SERVICE_TARGET}"
sudo systemctl daemon-reload
sudo systemctl enable "${SERVICE_NAME}"
sudo systemctl restart "${SERVICE_NAME}"
sudo systemctl status "${SERVICE_NAME}" --no-pager
