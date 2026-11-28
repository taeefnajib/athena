"""The Kubernetes runtime against a stand-in cluster: each "pod" is a local process running the real pod command
(bootstrap, shipped code, payload and outcome through the artifact store), so everything but the Kubernetes API runs."""
import json
import subprocess
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from athena.config import settings
from athena.connectors import kubernetes as kube
from athena.connectors import store
from athena.runtime import k8s_runtime
from athena.runtime.engine import run_spec
from athena.schemas.pipeline import PipelineSpec, Resources

BACKEND = Path(__file__).parents[1]


class FakeCluster:
    """BatchV1Api + CoreV1Api, just the calls Athena makes. A Job runs its container command as a local process."""

    def __init__(self) -> None:
        self.jobs: dict[str, dict] = {}
        self.procs: dict[str, subprocess.Popen] = {}
        self.deleted: list[str] = []

    # BatchV1Api
    def create_namespaced_job(self, namespace, body):
        name = body["metadata"]["name"]
        self.jobs[name] = body
        container = body["spec"]["template"]["spec"]["containers"][0]
        if container["image"] == "registry.example/missing:1":
            return  # the image can't be pulled: the pod stays pending
        cmd = [sys.executable if c == "python" else c for c in container["command"]]
        self.procs[name] = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    def read_namespaced_job_status(self, name, namespace):
        proc = self.procs.get(name)
        code = proc.poll() if proc else None
        return SimpleNamespace(status=SimpleNamespace(succeeded=1 if code == 0 else None, failed=1 if code not in (0, None) else None,
                                                      active=1 if code is None else None))

    def delete_namespaced_job(self, name, namespace, propagation_policy=None):
        self.deleted.append(name)
        if name in self.procs and self.procs[name].poll() is None:
            self.procs[name].kill()
            self.procs[name].wait(10)

    # CoreV1Api
    def list_namespaced_pod(self, namespace, label_selector):
        name = label_selector.split("=", 1)[1]
        if name not in self.jobs:
            return SimpleNamespace(items=[])
        if name not in self.procs:
            state = SimpleNamespace(waiting=SimpleNamespace(reason="ImagePullBackOff", message="pull access denied"), terminated=None)
        elif self.procs[name].poll() not in (0, None):
            state = SimpleNamespace(waiting=None, terminated=SimpleNamespace(reason="Error"))
        else:
            state = SimpleNamespace(waiting=None, terminated=None)
        return SimpleNamespace(items=[SimpleNamespace(metadata=SimpleNamespace(name=f"{name}-pod"),
                                                      status=SimpleNamespace(container_statuses=[SimpleNamespace(state=state)]))])

    def read_namespaced_pod_log(self, pod, namespace, tail_lines=20):
        proc = self.procs.get(pod.removesuffix("-pod"))
        return proc.stdout.read() if proc and proc.poll() is not None else ""


@pytest.fixture
def cluster(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(k8s_runtime, "POLL_S", 0.2)
    fake = FakeCluster()
    monkeypatch.setattr(kube, "clients", lambda cfg: (fake, fake))
    store.save_connection("cluster", "kubernetes", {"namespace": "ml", "image": "python:3.11-slim",
                                                    "artifacts": str(tmp_path / "artifacts"), "env_secret": "s3-creds"})
    yield fake
    for p in fake.procs.values():
        if p.poll() is None:
            p.kill()


def _n(nid, ntype, runtime=None, resources=None, **config):
    return {"id": nid, "type": ntype, "position": {"x": 0, "y": 0}, "config": config, "runtime": runtime, "resources": resources}


def _e(eid, s, t, sp=0, tp=0):
    return {"id": eid, "source": s, "target": t, "source_port": sp, "target_port": tp}


def _spec(runtime=None, resources=None) -> PipelineSpec:
    return PipelineSpec.model_validate({"name": "k8s", "nodes": [
        _n("csv", "csv_loader", path=str(BACKEND / "data.csv")), _n("imp", "imputer", strategy="median"),
        _n("tt", "train_test"), _n("rf", "rf", runtime, resources, n_estimators=25), _n("met", "metrics")],
        "edges": [_e("a", "csv", "imp"), _e("b", "imp", "tt"), _e("c", "tt", "rf", 0, 0), _e("d", "tt", "rf", 1, 1),
                  _e("e", "rf", "met", 0, 0), _e("f", "tt", "met", 2, 1), _e("g", "tt", "met", 3, 2)]})


def _run(spec: PipelineSpec, cache: Path) -> tuple[str, list[dict], dict]:
    events: list[dict] = []
    artifacts: dict = {}
    status = run_spec(spec, str(uuid.uuid4()), events.append, lambda: False, cache / "c", artifacts_out=artifacts)
    return status, events, artifacts


def test_manifest():
    cfg = kube.KubernetesConfig(image="ghcr.io/me/runner:1", service_account="athena", env_secret="s3", image_pull_secret="ghcr")
    m = k8s_runtime.job_manifest(cfg, "athena-x", ["python", "-c", "..."], Resources(cpu=2, memory_gb=4, gpu=1), 600, {"a": "b"})
    pod = m["spec"]["template"]["spec"]
    c = pod["containers"][0]
    assert c["resources"] == {"requests": {"cpu": "2", "memory": "4096Mi"}, "limits": {"memory": "4096Mi", "nvidia.com/gpu": "1"}}
    assert c["envFrom"] == [{"secretRef": {"name": "s3"}}] and pod["serviceAccountName"] == "athena"
    assert pod["imagePullSecrets"] == [{"name": "ghcr"}] and pod["restartPolicy"] == "Never"
    assert m["spec"]["backoffLimit"] == 0 and m["spec"]["activeDeadlineSeconds"] == 600
    name = k8s_runtime.job_name("1234ABCD-ffff", "Sub.Inner_Node")
    assert name.startswith("athena-1234abcd-sub-inner-node-") and len(name) <= 63


def test_k8s_runtime_gives_the_same_results(cluster: FakeCluster, tmp_path: Path):
    local_status, _, local = _run(_spec(), tmp_path / "local")
    status, events, remote = _run(_spec("k8s:cluster", {"cpu": 1, "memory_gb": 2}), tmp_path / "k8s")
    assert local_status == status == "completed", [e for e in events if e.get("status") == "error"]
    assert remote[("met", 0)] == local[("met", 0)]
    logs = [e["msg"] for e in events if e["type"] == "node_log" and e["node_id"] == "rf"]
    assert any(m.startswith("Submitted Kubernetes Job athena-") and "namespace ml" in m for m in logs)
    assert any("Running on Kubernetes pod" in m for m in logs) and any("Fit complete" in m for m in logs)
    (job,) = cluster.jobs.values()
    container = job["spec"]["template"]["spec"]["containers"][0]
    assert container["resources"]["requests"] == {"cpu": "1", "memory": "2048Mi"} and container["envFrom"][0]["secretRef"]["name"] == "s3-creds"
    assert container["command"][-1].endswith("athena-code.zip")  # Athena's code shipped with the job
    assert list(cluster.deleted) == list(cluster.jobs)  # the finished Job is deleted
    run_dirs = [p for p in (tmp_path / "artifacts").iterdir()]
    assert [p.name for p in run_dirs[0].iterdir()] == ["athena-code.zip"]  # the node's payload and outcome are cleaned up


def test_failures_are_explained(cluster: FakeCluster, tmp_path: Path):
    bad = PipelineSpec.model_validate({"name": "bad", "nodes": [
        _n("csv", "csv_loader", path=str(BACKEND / "data.csv")), _n("boom", "custom_code", "k8s:cluster", code="raise ValueError('bad rows')")],
        "edges": [_e("a", "csv", "boom")]})
    status, events, _ = _run(bad, tmp_path / "a")
    err = next(e for e in events if e["type"] == "node_finish" and e["status"] == "error")["error"]
    assert status == "error" and "bad rows" in err["message"] and "advanced.py" in err["traceback"]  # the handler's error, from the pod

    store.save_connection("cluster", "kubernetes", {"namespace": "ml", "image": "registry.example/missing:1",
                                                    "artifacts": str(tmp_path / "artifacts"), "ship_athena": False})
    status, events, _ = _run(_spec("k8s:cluster"), tmp_path / "b")
    err = next(e for e in events if e["type"] == "node_finish" and e["status"] == "error")["error"]["message"]
    assert "ImagePullBackOff: pull access denied" in err  # fails fast instead of waiting for the deadline
    assert cluster.deleted[-1] in err

    store.save_connection("cluster", "kubernetes", {"namespace": "ml", "image": "python:3.11-slim", "artifacts": ""})
    status, events, _ = _run(_spec("k8s:cluster"), tmp_path / "c")
    assert "no artifact store" in next(e for e in events if e["type"] == "node_finish" and e["status"] == "error")["error"]["message"]


def test_stop_deletes_the_job(cluster: FakeCluster, tmp_path: Path):
    spec = PipelineSpec.model_validate({"name": "slow", "nodes": [
        _n("csv", "csv_loader", path=str(BACKEND / "data.csv")), _n("wait", "custom_code", "k8s:cluster", code="import time; time.sleep(60); return df")],
        "edges": [_e("a", "csv", "wait")]})
    events: list[dict] = []
    stop = {"now": False}

    def emit(e: dict) -> None:
        events.append(e)
        if e["type"] == "node_log" and e["msg"].startswith("Submitted Kubernetes Job"):
            stop["now"] = True

    assert run_spec(spec, str(uuid.uuid4()), emit, lambda: stop["now"], tmp_path / "s" / "c") in ("cancelled", "error")
    assert cluster.deleted and all(p.poll() is not None for p in cluster.procs.values())


def test_runtime_validation(cluster: FakeCluster):
    from athena.runtime import adapters
    with pytest.raises(adapters.RuntimeUnavailable, match="needs a Kubernetes connection"):
        adapters.parse("k8s")
    store.save_connection("r", "ray", {"address": "auto"})
    with pytest.raises(adapters.RuntimeUnavailable, match="not a Kubernetes cluster connection"):
        adapters.check("k8s:r")
    from fastapi.testclient import TestClient

    from athena.main import app
    values = [r["value"] for r in TestClient(app).get("/api/runtimes").json()["runtimes"]]
    assert "k8s:cluster" in values and "ray:r" in values
    assert json.dumps(values)  # serialisable
