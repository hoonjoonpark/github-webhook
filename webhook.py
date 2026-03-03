from __future__ import annotations

import html
import hashlib
import hmac
import json
import logging
import os
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
import yaml
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("github-webhook")

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "").strip()
CONFIG_DIR = Path(os.environ.get("CONFIG_DIR", "deploy-configs")).expanduser()
BOT_ENDPOINT = os.environ.get("BOT_ENDPOINT", "").strip()
REQUEST_TIMEOUT = float(os.environ.get("REQUEST_TIMEOUT", "10"))
DEFAULT_SHELL = os.environ.get("DEPLOY_SHELL", "bash")
DEFAULT_HOST = os.environ.get("HOST", "127.0.0.1")
DEFAULT_PORT = int(os.environ.get("PORT", "9000"))

app = FastAPI(title="GitHub App Webhook")
_target_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


@dataclass(slots=True)
class DeploymentTarget:
    name: str
    display_name: str
    repository: str
    branches: set[str]
    workdir: Path
    commands: list[str]
    env: dict[str, str]
    notify: bool = True
    enabled: bool = True

    def matches(self, repository: str, ref: str, branch: str) -> bool:
        if not self.enabled or self.repository != repository:
            return False
        return ref in self.branches or branch in self.branches


def verify_github_signature(secret: str, body: bytes, sig_header: str | None) -> None:
    if not sig_header or not sig_header.startswith("sha256="):
        raise HTTPException(status_code=401, detail="Missing/invalid X-Hub-Signature-256")

    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    actual = sig_header.split("=", 1)[1].strip()
    if not hmac.compare_digest(expected, actual):
        raise HTTPException(status_code=401, detail="Invalid signature")


def send_bot_message(message: str) -> None:
    if not BOT_ENDPOINT:
        return

    try:
        response = requests.post(
            BOT_ENDPOINT,
            json={"message": message, "parse_mode": "HTML"},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
    except requests.RequestException:
        logger.exception("bot notification failed")


def normalize_branch(ref: str) -> str:
    prefix = "refs/heads/"
    return ref[len(prefix):] if ref.startswith(prefix) else ref


def expand_env(value: Any) -> Any:
    if isinstance(value, str):
        return os.path.expandvars(value)
    if isinstance(value, list):
        return [expand_env(item) for item in value]
    if isinstance(value, dict):
        return {key: expand_env(item) for key, item in value.items()}
    return value


def load_targets() -> list[DeploymentTarget]:
    if not CONFIG_DIR.exists():
        logger.warning("config dir does not exist: %s", CONFIG_DIR)
        return []

    targets: list[DeploymentTarget] = []
    for path in sorted(list(CONFIG_DIR.glob("*.yml")) + list(CONFIG_DIR.glob("*.yaml"))):
        raw = yaml.safe_load(path.read_text()) or {}
        documents = raw if isinstance(raw, list) else [raw]
        for index, item in enumerate(documents):
            if not isinstance(item, dict):
                raise ValueError(f"{path} item #{index + 1} must be a mapping")

            config = expand_env(item)
            repository = str(config.get("repository", "")).strip()
            if not repository:
                raise ValueError(f"{path} item #{index + 1} is missing repository")

            commands = config.get("commands") or []
            if not isinstance(commands, list) or not commands:
                raise ValueError(f"{path} item #{index + 1} must define commands")

            branches = {
                str(branch).strip()
                for branch in config.get("branches", [])
                if str(branch).strip()
            }
            if not branches:
                raise ValueError(f"{path} item #{index + 1} must define branches")

            workdir = Path(str(config.get("workdir", "."))).expanduser()
            target_name = str(config.get("name") or f"{path.stem}-{index + 1}")
            display_name = str(config.get("display_name") or target_name)
            env = {
                str(key): str(value)
                for key, value in (config.get("env") or {}).items()
            }
            targets.append(
                DeploymentTarget(
                    name=target_name,
                    display_name=display_name,
                    repository=repository,
                    branches=branches,
                    workdir=workdir,
                    commands=[str(command) for command in commands],
                    env=env,
                    notify=bool(config.get("notify", True)),
                    enabled=bool(config.get("enabled", True)),
                )
            )
    return targets


def find_matching_targets(repository: str, ref: str) -> list[DeploymentTarget]:
    branch = normalize_branch(ref)
    try:
        targets = load_targets()
    except Exception as exc:
        logger.exception("failed to load deploy configs")
        raise HTTPException(status_code=500, detail=f"Failed to load deploy configs: {exc}") from exc

    return [target for target in targets if target.matches(repository, ref, branch)]


def get_target_lock(target_name: str) -> threading.Lock:
    with _locks_guard:
        return _target_locks.setdefault(target_name, threading.Lock())


def format_bot_message(
    status: str,
    target: DeploymentTarget,
    context: dict[str, str],
    extra: str | None = None,
) -> str:
    title_map = {
        "start": "배포 시작",
        "done": "배포 완료",
        "failed": "배포 실패",
        "skipped": "배포 건너뜀",
    }
    title = title_map.get(status, "Deploy Update")
    lines = [
        f"<b>{html.escape(title)}</b>",
        f"서비스: <b>{html.escape(target.display_name)}</b>",
        f"타깃: <code>{html.escape(target.name)}</code>",
        f"저장소: <code>{html.escape(context['REPOSITORY'])}</code>",
        f"브랜치: <code>{html.escape(context['BRANCH'])}</code>",
        f"전달 ID: <code>{html.escape(context['DELIVERY_ID'] or '-')}</code>",
    ]
    if extra:
        lines.append(f"상세: <code>{html.escape(extra)}</code>")
    return "\n".join(lines)


def run_target(target: DeploymentTarget, context: dict[str, str]) -> None:
    lock = get_target_lock(target.name)
    if not lock.acquire(blocking=False):
        logger.warning("target %s is already running", target.name)
        if target.notify:
            send_bot_message(format_bot_message("skipped", target, context, "reason: already running"))
        return

    try:
        env = os.environ.copy()
        env.update(target.env)
        env.update(context)

        start_message = (
            f"[deploy] start target={target.name} repo={context['REPOSITORY']} "
            f"branch={context['BRANCH']} delivery={context['DELIVERY_ID']}"
        )
        logger.info(start_message)
        if target.notify:
            send_bot_message(format_bot_message("start", target, context))

        for command in target.commands:
            logger.info("running target=%s command=%s", target.name, command)
            result = subprocess.run(
                [DEFAULT_SHELL, "-lc", command],
                cwd=target.workdir,
                env=env,
                check=True,
                text=True,
                capture_output=True,
            )
            if result.stdout.strip():
                logger.info("target=%s stdout\n%s", target.name, result.stdout.strip())
            if result.stderr.strip():
                logger.info("target=%s stderr\n%s", target.name, result.stderr.strip())

        done_message = f"[deploy] done target={target.name} delivery={context['DELIVERY_ID']}"
        logger.info(done_message)
        if target.notify:
            send_bot_message(format_bot_message("done", target, context))
    except subprocess.CalledProcessError as exc:
        if exc.stdout:
            logger.error("target=%s stdout\n%s", target.name, exc.stdout.strip())
        if exc.stderr:
            logger.error("target=%s stderr\n%s", target.name, exc.stderr.strip())
        failed_message = f"[deploy] failed target={target.name} delivery={context['DELIVERY_ID']} exit={exc.returncode}"
        logger.exception(failed_message)
        if target.notify:
            send_bot_message(format_bot_message("failed", target, context, f"exit: {exc.returncode}"))
    except Exception as exc:
        failed_message = f"[deploy] failed target={target.name} delivery={context['DELIVERY_ID']} err={exc}"
        logger.exception(failed_message)
        if target.notify:
            send_bot_message(format_bot_message("failed", target, context, f"error: {exc}"))
    finally:
        lock.release()


@app.get("/healthz")
def healthz() -> PlainTextResponse:
    return PlainTextResponse("ok", status_code=200)


@app.get("/targets")
def list_targets() -> JSONResponse:
    payload = [
        {
            "name": target.name,
            "display_name": target.display_name,
            "repository": target.repository,
            "branches": sorted(target.branches),
            "workdir": str(target.workdir),
            "enabled": target.enabled,
            "notify": target.notify,
        }
        for target in load_targets()
    ]
    return JSONResponse(payload)


@app.post("/git")
async def github_webhook(request: Request, background: BackgroundTasks) -> PlainTextResponse:
    if not WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="WEBHOOK_SECRET is not set")

    event = request.headers.get("X-GitHub-Event", "")
    if event == "ping":
        return PlainTextResponse("pong", status_code=200)
    if event != "push":
        return PlainTextResponse("ignored", status_code=200)

    body = await request.body()
    verify_github_signature(WEBHOOK_SECRET, body, request.headers.get("X-Hub-Signature-256"))

    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc

    repository = str((payload.get("repository") or {}).get("full_name") or "").strip()
    ref = str(payload.get("ref") or "").strip()
    delivery_id = str(request.headers.get("X-GitHub-Delivery") or "")
    after = str(payload.get("after") or "")

    if not repository or not ref:
        raise HTTPException(status_code=400, detail="Missing repository/ref in payload")

    matches = find_matching_targets(repository, ref)
    if not matches:
        logger.info("ignored delivery=%s repo=%s ref=%s", delivery_id, repository, ref)
        return PlainTextResponse("ignored", status_code=200)

    branch = normalize_branch(ref)
    context = {
        "AFTER_SHA": after,
        "BRANCH": branch,
        "DELIVERY_ID": delivery_id,
        "GITHUB_EVENT": event,
        "REF": ref,
        "REPOSITORY": repository,
    }
    for target in matches:
        background.add_task(run_target, target, context)

    logger.info(
        "accepted delivery=%s repo=%s ref=%s targets=%s",
        delivery_id,
        repository,
        ref,
        ",".join(target.name for target in matches),
    )
    return PlainTextResponse("ok", status_code=200)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("webhook:app", host=DEFAULT_HOST, port=DEFAULT_PORT)
