"""Build a model bundle into a Docker image or a Bento, in the background.

Each build is the user's own tool (`docker build`, `bentoml build`) run in the bundle folder as a separate process,
its output written to `<bundle>/build.log`. One build per bundle at a time; builds stop when Athena stops. The last
finished build is remembered in `<bundle>/build.json`, so the Serving window still shows it after a restart.
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from athena.serving.bundle import bundle_path

Target = Literal["docker", "bento", "push"]
TARGETS: tuple[Target, ...] = ("docker", "bento", "push")
IMAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@-]{0,254}$")  # an image reference; never starts with "-"
LOG_TAIL = 80
# Tests point a tool at a stand-in command; None means "not installed".
TOOL_OVERRIDES: dict[str, list[str] | None] = {}


class BuildError(Exception):
    """The build can't start: unknown target, tool missing, or an old bundle."""


class BuildBusy(BuildError):
    """A build of this bundle is already running."""


@dataclass
class Build:
    slug: str
    target: Target
    command: list[str]
    tag: str
    process: subprocess.Popen[bytes]
    path: Path
    started: float
    finished: float | None = None
    cancelled: bool = False


_BUILDS: dict[str, Build] = {}


def _tool(target: Target) -> list[str] | None:
    name = "bentoml" if target == "bento" else "docker"
    if name in TOOL_OVERRIDES:
        return TOOL_OVERRIDES[name]
    found = shutil.which(name)
    if found:
        return [found]
    if name == "bentoml" and importlib.util.find_spec("bentoml") is not None:
        return [sys.executable, "-m", "bentoml"]
    return None


def tools() -> dict[str, dict[str, Any]]:
    """Which build tools are installed (not whether Docker's daemon is running: the build log says so)."""
    hints = {"docker": "Install Docker Desktop (or Docker Engine) and make sure `docker` is on your PATH.",
             "bento": "Install BentoML in Athena's environment: `uv pip install bentoml`."}
    out = {}
    for target in ("docker", "bento"):
        cmd = _tool(target)
        out[target] = {"available": cmd is not None, "command": " ".join(cmd) if cmd else None, "hint": None if cmd else hints[target]}
    return out


def _command(target: Target, tool: list[str], slug: str, image: str) -> tuple[list[str], str]:
    if target == "docker":
        tag = image or f"{slug}:latest"
        return [*tool, "build", "-t", tag, "."], tag
    if target == "push":
        return [*tool, "push", image], image
    return [*tool, "build", "-f", "bentofile.yaml", "."], ""  # BentoML names the Bento itself; read from the log


def last_image(slug: str) -> str:
    """The image of the bundle's last successful Docker build or push ("" if none)."""
    saved = bundle_path(slug) / "build.json"
    if not saved.exists():
        return ""
    record = json.loads(saved.read_text(encoding="utf-8"))
    return str(record.get("tag", "")) if record.get("state") == "succeeded" and record.get("target") in ("docker", "push") else ""


def run_command(target: str, tag: str) -> str:
    if not tag:
        return ""
    return f"bentoml serve {tag}" if target == "bento" else f"docker run --rm -p 8000:8000 {tag}"


def start(slug: str, target: str, image: str = "") -> dict[str, Any]:
    """Build a Docker image (named ``image``, default ``<slug>:latest``), build a Bento, or push an image."""
    if target not in TARGETS:
        raise BuildError(f"Unknown build target {target!r}: use one of {', '.join(TARGETS)}")
    kind: Target = "docker" if target == "docker" else "push" if target == "push" else "bento"
    image = image.strip()
    if kind == "push" and not image:
        image = last_image(slug)
        if not image:
            raise BuildError("Build the Docker image first (with your registry in its name, e.g. ghcr.io/you/model:1)")
    if image and not IMAGE_RE.match(image):
        raise BuildError(f"{image!r} isn't a valid image name (e.g. ghcr.io/you/churn-model:1)")
    path = bundle_path(slug)
    current = _BUILDS.get(path.name)
    if current and current.process.poll() is None:
        raise BuildBusy(f"A {current.target} build of {path.name} is already running")
    tool = _tool(kind)
    if tool is None:
        raise BuildError(tools()["bento" if kind == "bento" else "docker"]["hint"])
    if target == "bento" and not (path / "bentofile.yaml").exists():
        raise BuildError("This bundle has no bentofile.yaml (it was made by an older Athena): deploy the model again")
    cmd, tag = _command(kind, tool, path.name, image)
    log = open(path / "build.log", "wb")  # noqa: SIM115 - handed to the child, closed when it ends
    log.write(f"$ {' '.join(cmd)}\n".encode())
    log.flush()
    try:
        proc = subprocess.Popen(cmd, cwd=path, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
    except OSError as exc:
        log.close()
        raise BuildError(f"Couldn't start {cmd[0]}: {exc}") from exc
    log.close()  # the child holds its own handle
    _BUILDS[path.name] = Build(path.name, kind, cmd, tag, proc, path, time.time())
    return status(path.name) or {}


def _tail(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-LOG_TAIL:]
    except OSError:
        return []


_BENTO_TAG = re.compile(r'Bento\(tag="([^"]+)"\)')


def _finish(b: Build) -> None:
    b.finished = time.time()
    lines = _tail(b.path / "build.log")
    if b.target == "bento" and not b.tag:
        found = [m.group(1) for line in lines for m in [_BENTO_TAG.search(line)] if m]
        b.tag = found[-1] if found else ""
    state = "cancelled" if b.cancelled else ("succeeded" if b.process.returncode == 0 else "failed")
    record = {"target": b.target, "state": state, "tag": b.tag if state == "succeeded" else "",
              "started": b.started, "finished": b.finished, "returncode": b.process.returncode}
    (b.path / "build.json").write_text(json.dumps(record, indent=2), encoding="utf-8")


def status(slug: str) -> dict[str, Any] | None:
    """The current or last build of a bundle, or None if it was never built."""
    try:
        path = bundle_path(slug)
    except Exception:  # noqa: BLE001 - a deleted bundle has no build
        return None
    b = _BUILDS.get(path.name)
    if b is not None:
        code = b.process.poll()
        if code is not None and b.finished is None:
            _finish(b)
        if code is None:
            state, tag = "running", b.tag
        else:
            record = json.loads((path / "build.json").read_text(encoding="utf-8"))
            state, tag = record["state"], record["tag"]
        return {"target": b.target, "state": state, "tag": tag, "started": b.started, "finished": b.finished,
                "command": " ".join(b.command), "run_command": run_command(b.target, tag) if state == "succeeded" else "",
                "log": _tail(path / "build.log")}
    saved = path / "build.json"
    if not saved.exists():
        return None
    record = json.loads(saved.read_text(encoding="utf-8"))
    return {**record, "command": "", "run_command": run_command(record["target"], record["tag"]) if record["state"] == "succeeded" else "",
            "log": _tail(path / "build.log")}


def cancel(slug: str) -> None:
    b = _BUILDS.get(bundle_path(slug).name)
    if b is not None and b.process.poll() is None:
        b.cancelled = True
        b.process.terminate()
        try:
            b.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            b.process.kill()
            b.process.wait()
        _finish(b)


def stop_all() -> None:
    for slug in list(_BUILDS):
        try:
            cancel(slug)
        except Exception:  # noqa: BLE001, S112 - shutting down: a bundle deleted meanwhile has nothing to stop
            continue
    _BUILDS.clear()
