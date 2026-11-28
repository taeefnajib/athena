"""Local prediction endpoints: each bundle's service.py in its own process, bound to 127.0.0.1.

The model is unpickled only in that process, never in the API server. Endpoints stop when Athena stops.
"""
from __future__ import annotations

import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from athena.serving.bundle import bundle_path

START_TIMEOUT_S = 60


@dataclass
class Endpoint:
    slug: str
    port: int
    process: subprocess.Popen[bytes]
    started: float = field(default_factory=time.time)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def alive(self) -> bool:
        return self.process.poll() is None


_ENDPOINTS: dict[str, Endpoint] = {}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _request(url: str, body: dict[str, Any] | None = None, timeout: float = 30) -> tuple[int, Any]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read() or b"null")
        except json.JSONDecodeError:
            return exc.code, {"detail": exc.reason}


def start(slug: str) -> dict[str, Any]:
    path = bundle_path(slug)
    existing = _ENDPOINTS.get(path.name)
    if existing and existing.alive():
        return status(path.name)
    port = _free_port()
    log = open(path / "endpoint.log", "wb")  # noqa: SIM115 - kept open for the child's lifetime
    # stdin stays open for the child's lifetime: if Athena dies, the pipe closes and the service exits too
    cmd = [sys.executable, "service.py", "--host", "127.0.0.1", "--port", str(port), "--exit-with-parent"]
    if "--log-requests" in (path / "service.py").read_text(encoding="utf-8"):  # bundles made before monitoring can't
        cmd += ["--log-requests", str(request_log(path))]
    proc = subprocess.Popen(cmd, cwd=path, stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT)
    ep = Endpoint(path.name, port, proc)
    deadline = time.time() + START_TIMEOUT_S
    while time.time() < deadline:
        if not ep.alive():
            log.close()
            tail = (path / "endpoint.log").read_text(encoding="utf-8", errors="replace").strip().splitlines()[-5:]
            raise RuntimeError("The service stopped while starting: " + (" | ".join(tail) or "no output"))
        try:
            code, _ = _request(f"{ep.url}/health", timeout=2)
            if code == 200:
                _ENDPOINTS[path.name] = ep
                return status(path.name)
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
            pass
        time.sleep(0.3)
    proc.kill()
    raise RuntimeError(f"The service didn't answer within {START_TIMEOUT_S} s (see {path / 'endpoint.log'})")


def request_log(path: Path) -> Path:
    """Where a local endpoint logs its requests (the Endpoint Requests node reads it)."""
    return path / "logs" / "requests.jsonl"


def logged_requests(path: Path) -> int:
    total = 0
    for f in (request_log(path).with_suffix(".1.jsonl"), request_log(path)):
        if f.exists():
            with f.open("rb") as fh:
                total += sum(chunk.count(b"\n") for chunk in iter(lambda: fh.read(1 << 20), b""))
    return total


def stop(slug: str) -> None:
    ep = _ENDPOINTS.pop(slug, None)
    if ep and ep.alive():
        ep.process.terminate()
        try:
            ep.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            ep.process.kill()


def stop_all() -> None:
    for slug in list(_ENDPOINTS):
        stop(slug)


def status(slug: str) -> dict[str, Any]:
    ep = _ENDPOINTS.get(slug)
    if ep and not ep.alive():
        _ENDPOINTS.pop(slug, None)
        ep = None
    return {"running": ep is not None, "url": ep.url if ep else None, "port": ep.port if ep else None,
            "started": ep.started if ep else None, "metrics_url": f"{ep.url}/metrics" if ep else None}


def metrics(slug: str) -> str:
    """The running endpoint's Prometheus metrics, fetched for the Serving window."""
    ep = _ENDPOINTS.get(slug)
    if not ep or not ep.alive():
        raise RuntimeError("This endpoint isn't running: start it first")
    with urllib.request.urlopen(f"{ep.url}/metrics", timeout=10) as r:
        return str(r.read().decode("utf-8"))


def running() -> dict[str, dict[str, Any]]:
    return {slug: status(slug) for slug in list(_ENDPOINTS)}


def predict(slug: str, body: dict[str, Any]) -> tuple[int, Any]:
    ep = _ENDPOINTS.get(slug)
    if not ep or not ep.alive():
        raise RuntimeError("This endpoint isn't running: start it first")
    return _request(f"{ep.url}/predict", body)
