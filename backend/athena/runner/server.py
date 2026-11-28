"""The runner's HTTP API. Every request needs ``Authorization: Bearer <token>``.

    GET    /info                     what this machine offers (Athena version, CPUs, memory, GPUs, job slots)
    POST   /jobs                     body: the node's pickled payload -> {"job_id", "state"}
    GET    /jobs/{id}?since=N        {"state", "lines": log lines from N on, "error"}; state: queued | running | finished | failed
    GET    /jobs/{id}/outcome        the pickled (result, lines, error), once finished
    DELETE /jobs/{id}                stop the job (if running) and delete its files

Payloads are pickles, so whoever holds the token can run code here: that is the point of a runner, and why the
token is mandatory. Jobs run one per process (``athena.runner.job``), at most ``max_jobs`` at a time; the rest wait.
"""
from __future__ import annotations

import hmac
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import Response

TICK_S = 0.3


@dataclass
class Job:
    id: str
    dir: Path
    node: str
    created: float = field(default_factory=time.time)
    state: str = "queued"
    proc: subprocess.Popen[bytes] | None = None
    error: str = ""


def kill_tree(proc: subprocess.Popen[bytes]) -> None:
    """Stop a job and everything it started (a handler's joblib workers, for instance), not just its main process."""
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, check=False)
    else:
        import signal
        try:
            os.killpg(proc.pid, signal.SIGKILL)  # the job runs in its own process group
        except ProcessLookupError:
            pass
    try:
        proc.wait(10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(10)


def _gpus() -> int:
    try:
        out = subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True, timeout=10, check=False)
        return sum(1 for ln in out.stdout.splitlines() if ln.startswith("GPU "))
    except (OSError, subprocess.TimeoutExpired):
        return 0


def _memory_gb() -> float:
    try:
        import psutil  # optional
        return round(psutil.virtual_memory().total / 1024**3, 1)
    except ImportError:
        if hasattr(os, "sysconf") and "SC_PHYS_PAGES" in os.sysconf_names:
            return round(os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / 1024**3, 1)
        if os.name == "nt":
            import ctypes

            class _Status(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong),
                            ("avail", ctypes.c_ulonglong), ("page_total", ctypes.c_ulonglong), ("page_avail", ctypes.c_ulonglong),
                            ("virtual_total", ctypes.c_ulonglong), ("virtual_avail", ctypes.c_ulonglong), ("ext", ctypes.c_ulonglong)]
            st = _Status()
            st.length = ctypes.sizeof(_Status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):  # type: ignore[attr-defined]
                return round(st.total / 1024**3, 1)
        return 0.0  # unknown


def create_app(token: str, work_dir: Path, max_jobs: int = 1) -> FastAPI:
    if not token:
        raise ValueError("A runner needs a token")
    work_dir.mkdir(parents=True, exist_ok=True)
    jobs: dict[str, Job] = {}
    lock = threading.Lock()
    gpus = _gpus()

    def authorised(request: Request) -> None:
        given = request.headers.get("authorization", "")
        if not hmac.compare_digest(given.encode(), f"Bearer {token}".encode()):
            raise HTTPException(401, "Missing or wrong runner token")

    def tick() -> None:
        """Mark finished jobs, start waiting ones while slots are free."""
        with lock:
            for job in jobs.values():
                if job.state == "running" and job.proc is not None and job.proc.poll() is not None:
                    if job.proc.returncode == 0 and (job.dir / "outcome.pkl").exists():
                        job.state = "finished"
                    else:
                        tail = (job.dir / "stderr.log").read_text(encoding="utf-8", errors="replace").strip().splitlines()[-15:]
                        job.state, job.error = "failed", f"The job process exited with code {job.proc.returncode}" + (
                            ":\n" + "\n".join(tail) if tail else "")
            running = sum(1 for j in jobs.values() if j.state == "running")
            for job in sorted((j for j in jobs.values() if j.state == "queued"), key=lambda j: j.created):
                if running >= max_jobs:
                    break
                err = (job.dir / "stderr.log").open("wb")
                job.proc = subprocess.Popen([sys.executable, "-m", "athena.runner.job", str(job.dir)], cwd=job.dir,
                                            stdin=subprocess.DEVNULL, stdout=err, stderr=subprocess.STDOUT,
                                            start_new_session=os.name != "nt")  # its own process group, for kill_tree
                err.close()
                job.state = "running"
                running += 1

    stop = threading.Event()

    def loop() -> None:
        while not stop.wait(TICK_S):
            tick()

    app = FastAPI(title="Athena runner", dependencies=[Depends(authorised)])

    @app.on_event("startup")
    def _start() -> None:
        threading.Thread(target=loop, daemon=True).start()

    @app.on_event("shutdown")
    def _stop() -> None:
        stop.set()
        with lock:
            for job in jobs.values():
                if job.proc is not None:
                    kill_tree(job.proc)

    def get(job_id: str) -> Job:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, f"No job {job_id}")
        return job

    @app.get("/info")
    def info() -> dict[str, Any]:
        import athena
        with lock:
            states = [j.state for j in jobs.values()]
        return {"athena_version": getattr(athena, "__version__", "") or _version(), "python": sys.version.split()[0],
                "cpus": os.cpu_count() or 0, "memory_gb": _memory_gb(), "gpus": gpus, "max_jobs": max_jobs,
                "running": states.count("running"), "queued": states.count("queued")}

    @app.post("/jobs")
    async def submit(request: Request) -> dict[str, str]:
        body = await request.body()
        if not body:
            raise HTTPException(422, "Send the node's payload")
        job = Job(uuid.uuid4().hex, work_dir / uuid.uuid4().hex, request.headers.get("x-athena-node", ""))
        job.dir.mkdir(parents=True)
        (job.dir / "payload.pkl").write_bytes(body)
        with lock:
            jobs[job.id] = job
        tick()
        return {"job_id": job.id, "state": job.state}

    @app.get("/jobs/{job_id}")
    def status(job_id: str, since: int = 0) -> dict[str, Any]:
        tick()
        job = get(job_id)
        lines: list[Any] = []
        log = job.dir / "log.jsonl"
        if log.exists():
            import json
            for raw in log.read_text(encoding="utf-8").splitlines()[since:]:
                try:
                    lines.append(json.loads(raw))
                except ValueError:  # a line still being written
                    break
        return {"state": job.state, "lines": lines, "error": job.error}

    @app.get("/jobs/{job_id}/outcome")
    def outcome(job_id: str) -> Response:
        job = get(job_id)
        if job.state != "finished":
            raise HTTPException(409, f"The job is {job.state}")
        return Response((job.dir / "outcome.pkl").read_bytes(), media_type="application/octet-stream")

    @app.delete("/jobs/{job_id}")
    def delete(job_id: str) -> dict[str, bool]:
        with lock:  # forget it first, so the scheduler thread never reads its files while they're deleted
            job = jobs.pop(job_id, None)
        if job is None:
            raise HTTPException(404, f"No job {job_id}")
        if job.proc is not None:
            kill_tree(job.proc)
        for _ in range(20):  # Windows can hold a just-closed file for a moment
            shutil.rmtree(job.dir, ignore_errors=True)
            if not job.dir.exists():
                break
            time.sleep(0.1)
        return {"ok": True}

    return app


def _version() -> str:
    from importlib.metadata import PackageNotFoundError, version
    try:
        return version("athena-backend")
    except PackageNotFoundError:
        return ""
