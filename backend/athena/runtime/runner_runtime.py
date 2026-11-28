"""Run a node on an Athena runner (runtime ``"runner:<connection>"``): another machine running ``athena-runner``.

The worker POSTs the node's pickled payload, then polls the job every second: new log lines are shown as they
arrive (unlike Ray and Kubernetes, a runner streams them), Stop deletes the job (killing it on the runner), and
when it finishes the worker downloads the outcome and deletes the job. Requests carry the connection's token.
"""
from __future__ import annotations

import json
import pickle
import ssl
import time
import urllib.error
import urllib.request
from typing import Any

from athena.core.handler import ExecutionContext, HandlerResult
from athena.runtime import remote
from athena.schemas.pipeline import NodeSpec

POLL_S = 1.0
TIMEOUT_S = 60


class RunnerError(RuntimeError):
    """The runner refused or couldn't be reached."""


class RunnerClient:
    def __init__(self, url: str, token: str, verify_tls: bool = True) -> None:
        self.base = url.rstrip("/")
        self.token = token
        self.context = None if verify_tls else ssl._create_unverified_context()  # the user turned verification off

    def request(self, method: str, path: str, body: bytes | None = None, headers: dict[str, str] | None = None) -> bytes:
        req = urllib.request.Request(f"{self.base}{path}", data=body, method=method,
                                     headers={"Authorization": f"Bearer {self.token}", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S, context=self.context) as r:  # the user's own runner URL
                return bytes(r.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            try:
                detail = json.loads(detail).get("detail", detail)
            except ValueError:
                pass
            raise RunnerError(f"The runner answered {exc.code}: {detail}") from None
        except (urllib.error.URLError, OSError) as exc:
            raise RunnerError(f"Couldn't reach the runner at {self.base}: {getattr(exc, 'reason', exc)}") from None

    def json(self, method: str, path: str, body: bytes | None = None, headers: dict[str, str] | None = None) -> Any:
        return json.loads(self.request(method, path, body, headers) or b"null")


def client_for(cfg: Any) -> RunnerClient:
    token = cfg.token.get_secret_value() if hasattr(cfg.token, "get_secret_value") else str(cfg.token)
    if not cfg.url.strip():
        raise RunnerError("The runner connection has no URL")
    return RunnerClient(cfg.url, token, cfg.verify_tls)


def run(node: NodeSpec, ctx: ExecutionContext, connection: str) -> HandlerResult:
    from athena.config import settings
    from athena.connectors.store import resolve_connection
    if ctx.node_type == "custom_code" and not settings.allow_custom_code:  # the runner doesn't see our settings
        raise RuntimeError("Custom code is disabled (ATHENA_ALLOW_CUSTOM_CODE=false)")
    _, cfg = resolve_connection(connection)
    client = client_for(cfg)
    payload = pickle.dumps({"node_type": ctx.node_type, "config": ctx.config, "inputs": ctx.inputs,
                            "run_id": ctx.run_id, "node_id": ctx.node_id})
    job = client.json("POST", "/jobs", payload, {"Content-Type": "application/octet-stream", "X-Athena-Node": ctx.node_id})
    job_id = job["job_id"]
    ctx.logger.info(f"Sent to runner {client.base} (job {job_id[:8]}, {len(payload) / 1e6:.1f} MB)"
                    + (": waiting for a free slot" if job["state"] == "queued" else ""))
    shown = 0
    try:
        while True:
            if ctx.cancelled():
                raise RuntimeError("Cancelled: the job was stopped on the runner")
            st = client.json("GET", f"/jobs/{job_id}?since={shown}")
            for level, msg in st["lines"]:
                getattr(ctx.logger, level)(msg)
            shown += len(st["lines"])
            if st["state"] == "finished":
                break
            if st["state"] == "failed":
                raise RunnerError(st["error"] or "The job failed on the runner")
            time.sleep(POLL_S)
        outcome = pickle.loads(client.request("GET", f"/jobs/{job_id}/outcome"))  # from the user's own runner
    finally:
        try:
            client.request("DELETE", f"/jobs/{job_id}")  # stops it if still running, and frees its files
        except RunnerError:
            pass
    return remote.finish(ctx, outcome, already_shown=shown)
