"""Run a node as a Kubernetes Job (runtime ``"k8s:<connection>"``).

1. The worker pickles the node's payload (type, config, inputs) to the connection's artifact store.
2. It creates a Job: one pod running ``python -c BOOTSTRAP <payload> <outcome> [<code zip>]`` in the connection's
   image, with the node's resources as requests and limits (``nvidia.com/gpu`` for GPUs), the node's timeout as
   ``activeDeadlineSeconds``, and optionally Athena's code (uploaded once per run) when the image lacks it.
3. The pod runs the handler (``runtime/k8s_entry.py``) and writes ``(result, log lines, error)`` back.
4. The worker polls the Job every 2 s, fails fast on image or configuration errors, deletes the Job on Stop, and
   on success reads the outcome, replays the log lines, and deletes the Job and the node's artifacts.

A failed pod (not a failing handler, which comes back as an ordinary node error) is kept for an hour
(``ttlSecondsAfterFinished``) so ``kubectl logs`` can show what happened; its last log lines are in the error.
"""
from __future__ import annotations

import io
import pickle
import re
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any

from athena.core.handler import ExecutionContext, HandlerResult
from athena.runtime import remote
from athena.schemas.pipeline import NodeSpec, Resources

POLL_S = 2.0
FAILED_TTL_S = 3600
IMAGE_ERRORS = {"ErrImagePull", "ImagePullBackOff", "InvalidImageName", "CreateContainerConfigError", "CreateContainerError"}

BOOTSTRAP = """
import io, sys, tempfile, zipfile
payload, outcome, code = sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else ""
if code:  # Athena's code, shipped with the job: unpack it ahead of anything installed
    import fsspec
    with fsspec.open(code, "rb") as fh:
        data = fh.read()
    target = tempfile.mkdtemp(prefix="athena-")
    zipfile.ZipFile(io.BytesIO(data)).extractall(target)
    sys.path.insert(0, target)
from athena.runtime.k8s_entry import main
sys.exit(main(payload, outcome))
""".strip()

_SHIPPED: dict[str, str] = {}  # run id -> code zip url (uploaded once per run)


def job_name(run_id: str, node_id: str) -> str:
    """A DNS-1123 name, unique per attempt: athena-<run>-<node>-<random>."""
    node = re.sub(r"[^a-z0-9-]+", "-", node_id.lower()).strip("-")[:30] or "node"
    return f"athena-{run_id[:8].lower()}-{node}-{uuid.uuid4().hex[:5]}"


def resources_block(res: Resources | None) -> dict[str, dict[str, str]]:
    """Pod requests and limits. CPU and memory are requested (and memory limited); GPUs are limits, as Kubernetes requires."""
    if res is None:
        return {}
    requests: dict[str, str] = {}
    limits: dict[str, str] = {}
    if res.cpu:
        requests["cpu"] = f"{res.cpu:g}"
    if res.memory_gb:
        requests["memory"] = limits["memory"] = f"{int(res.memory_gb * 1024)}Mi"
    if res.gpu:
        limits["nvidia.com/gpu"] = str(res.gpu)
    return {k: v for k, v in (("requests", requests), ("limits", limits)) if v}


def job_manifest(cfg: Any, name: str, command: list[str], res: Resources | None, deadline_s: int, labels: dict[str, str]) -> dict[str, Any]:
    container: dict[str, Any] = {"name": "node", "image": cfg.image, "command": command, "env": [{"name": "PYTHONUNBUFFERED", "value": "1"}]}
    block = resources_block(res)
    if block:
        container["resources"] = block
    if cfg.env_secret:
        container["envFrom"] = [{"secretRef": {"name": cfg.env_secret}}]
    pod: dict[str, Any] = {"restartPolicy": "Never", "containers": [container]}
    if cfg.service_account:
        pod["serviceAccountName"] = cfg.service_account
    if cfg.image_pull_secret:
        pod["imagePullSecrets"] = [{"name": cfg.image_pull_secret}]
    return {
        "apiVersion": "batch/v1", "kind": "Job",
        "metadata": {"name": name, "labels": labels},
        "spec": {"backoffLimit": 0,  # Athena's own retry policy decides whether to try again
                 "activeDeadlineSeconds": deadline_s,  # the pod stops even if Athena isn't there to stop it
                 "ttlSecondsAfterFinished": FAILED_TTL_S,
                 "template": {"metadata": {"labels": labels}, "spec": pod}},
    }


class ArtifactStore:
    """Where payloads and outcomes are exchanged: Athena's filesystem view and the URL the pod opens."""

    def __init__(self, fs: Any, path: str, url: str) -> None:
        self.fs, self.path, self.url_base = fs, path.rstrip("/"), url.rstrip("/")

    def put(self, rel: str, data: bytes) -> str:
        target = f"{self.path}/{rel}"
        self.fs.makedirs(target.rsplit("/", 1)[0], exist_ok=True)
        with self.fs.open(target, "wb") as fh:
            fh.write(data)
        return f"{self.url_base}/{rel}"

    def get(self, rel: str) -> bytes:
        with self.fs.open(f"{self.path}/{rel}", "rb") as fh:
            return bytes(fh.read())

    def exists(self, rel: str) -> bool:
        return bool(self.fs.exists(f"{self.path}/{rel}"))

    def remove(self, rel: str) -> None:
        try:
            self.fs.rm(f"{self.path}/{rel}", recursive=True)
        except FileNotFoundError:
            pass


def store_for(cfg: Any) -> ArtifactStore:
    if not cfg.artifacts.strip():
        raise RuntimeError("The Kubernetes connection has no artifact store: set one (s3://bucket/athena, …) under Connections")
    if cfg.storage_connection:
        from athena.connectors import storage
        from athena.connectors.store import resolve_connection
        _, scfg = resolve_connection(cfg.storage_connection)
        return ArtifactStore(storage.filesystem(scfg), storage.full_path(scfg, cfg.artifacts), storage.url(scfg, cfg.artifacts))
    import fsspec
    fs, path = fsspec.core.url_to_fs(cfg.artifacts)
    return ArtifactStore(fs, path, cfg.artifacts)


def athena_zip() -> bytes:
    """Athena's package as a zip (``athena/...``), without bytecode."""
    import athena
    root = Path(athena.__file__).parent
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(root.rglob("*")):
            if f.is_file() and "__pycache__" not in f.parts and f.suffix != ".pyc":
                z.write(f, f"athena/{f.relative_to(root).as_posix()}")
    return buf.getvalue()


def _pod_problem(core: Any, namespace: str, name: str, with_logs: bool = False) -> tuple[str | None, str]:
    """(fatal waiting/termination reason or None, last log lines) of the Job's pod."""
    pods = core.list_namespaced_pod(namespace, label_selector=f"job-name={name}").items
    if not pods:
        return None, ""
    pod = pods[0]
    reason = None
    for st in pod.status.container_statuses or []:
        waiting = getattr(st.state, "waiting", None)
        terminated = getattr(st.state, "terminated", None)
        if waiting is not None and waiting.reason in IMAGE_ERRORS:
            reason = f"{waiting.reason}: {waiting.message or ''}".strip(": ")
        elif terminated is not None and terminated.reason and terminated.reason != "Completed":
            reason = terminated.reason  # e.g. OOMKilled, DeadlineExceeded, Error
    if not with_logs:
        return reason, ""
    try:
        logs = core.read_namespaced_pod_log(pod.metadata.name, namespace, tail_lines=20) or ""
    except Exception:  # noqa: BLE001 - a pod that never started has no logs
        logs = ""
    return reason, logs.strip()


def _delete(batch: Any, namespace: str, name: str) -> None:
    try:
        batch.delete_namespaced_job(name, namespace, propagation_policy="Background")
    except Exception:  # noqa: BLE001, S110 - already gone, or the cluster is unreachable: its deadline still stops it
        pass


def run(node: NodeSpec, ctx: ExecutionContext, connection: str) -> HandlerResult:
    from athena.config import settings
    from athena.connectors import kubernetes as kube
    from athena.connectors.store import resolve_connection
    if ctx.node_type == "custom_code" and not settings.allow_custom_code:  # the cluster doesn't see our settings
        raise RuntimeError("Custom code is disabled (ATHENA_ALLOW_CUSTOM_CODE=false)")
    _, cfg = resolve_connection(connection)
    if not cfg.image.strip():  # type: ignore[attr-defined]
        raise RuntimeError(f"The Kubernetes connection {connection!r} has no container image: set one under Connections")
    store = store_for(cfg)
    name = job_name(ctx.run_id, ctx.node_id)
    payload = {"node_type": ctx.node_type, "config": ctx.config, "inputs": ctx.inputs, "run_id": ctx.run_id, "node_id": ctx.node_id}
    payload_url = store.put(f"{ctx.run_id}/{name}/payload.pkl", pickle.dumps(payload))
    outcome_url = f"{store.url_base}/{ctx.run_id}/{name}/outcome.pkl"
    command = ["python", "-c", BOOTSTRAP, payload_url, outcome_url]
    if cfg.ship_athena:  # type: ignore[attr-defined]
        if ctx.run_id not in _SHIPPED:
            _SHIPPED[ctx.run_id] = store.put(f"{ctx.run_id}/athena-code.zip", athena_zip())
        command.append(_SHIPPED[ctx.run_id])
    deadline = node.timeout_s or settings.node_timeout_s
    labels = {"app.kubernetes.io/managed-by": "athena", "athena/run": ctx.run_id[:63],
              "athena/node": re.sub(r"[^A-Za-z0-9_.-]", "-", ctx.node_id)[:63]}
    batch, core = kube.clients(cfg)  # type: ignore[arg-type]
    namespace = cfg.namespace  # type: ignore[attr-defined]
    batch.create_namespaced_job(namespace, job_manifest(cfg, name, command, node.resources, deadline, labels))
    asked = resources_block(node.resources)
    ctx.logger.info(f"Submitted Kubernetes Job {name} in namespace {namespace} (image {cfg.image}"  # type: ignore[attr-defined]
                    + (f", {asked}" if asked else "") + ")")
    while True:
        if ctx.cancelled():
            _delete(batch, namespace, name)
            raise RuntimeError(f"Cancelled: Kubernetes Job {name} was deleted")
        status = batch.read_namespaced_job_status(name, namespace).status
        if status.succeeded:
            break
        # a pending pod counts as active, so look at it every time: a wrong image never fails the Job by itself
        reason, _ = _pod_problem(core, namespace, name)
        stuck = bool(reason) and reason.split(":")[0] in IMAGE_ERRORS
        if status.failed or stuck:
            if stuck:  # don't wait for the deadline
                _delete(batch, namespace, name)
            _, logs = _pod_problem(core, namespace, name, with_logs=True)
            tail = f"\nLast pod log lines:\n{logs}" if logs else ""
            kept = "" if stuck else f" It's kept for an hour: kubectl logs -n {namespace} job/{name}"
            raise RuntimeError(f"Kubernetes Job {name} failed{f' ({reason})' if reason else ''}.{kept}{tail}")
        time.sleep(POLL_S)
    if not store.exists(f"{ctx.run_id}/{name}/outcome.pkl"):
        raise RuntimeError(f"Kubernetes Job {name} finished but wrote no result to {outcome_url}: can the pod write to the artifact store?")
    outcome = pickle.loads(store.get(f"{ctx.run_id}/{name}/outcome.pkl"))
    _delete(batch, namespace, name)
    store.remove(f"{ctx.run_id}/{name}")
    return remote.finish(ctx, outcome)
